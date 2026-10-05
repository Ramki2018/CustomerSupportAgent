# Component Architecture

The system is a **small multi-agent design inside one LangGraph workflow**: a deterministic
**supervisor** hands each request to a **policy agent** (retrieval + LLM, no tools), an
**order agent** (LLM + order tools, no policy documents), or both. Agents never call each
other; they communicate only through shared graph state. Components are plain Python modules
that the graph nodes call. (The `agents/` folder is a separate class chain
`LLMAgent -> RagAgent -> ToolAgent -> FullAgent` showing how the system was built in phases.)

## 1. Component view

```mermaid
flowchart LR
    C["Customer"] -->|"POST /chat"| API

    subgraph API_LAYER["API layer - deployment/app.py"]
        API["FastAPI<br/>/chat  /feedback  /health<br/>input validation, request lock"]
    end

    subgraph ORCH["Orchestration - LangGraph StateGraph (graph/app.py)"]
        FA["FullAgent facade<br/>agents/full_agent.py"]
        N1["redact_pii"] --> N2{"safety_check"}
        N2 -- "unsafe" --> NE["escalate"]
        N2 -- "safe" --> N3["resolve_memory"]
        N3 --> SUP{"supervisor<br/>deterministic router"}
        SUP -- "policy / mixed" -->         PA["policy_agent<br/>retrieval + LLM<br/>NO tools<br/>skips the LLM if retrieval is weak"]
        SUP -- "order" --> OA["order_agent<br/>LLM + order tools<br/>NO documents"]
        PA -- "mixed" --> OA
        PA -- "tool call attempted" --> NE
        PA -- "policy reply" --> N7["finalize"]
        OA -- "tool calls" --> N6["tools<br/>allow-listed, capped"]
        N6 -- "continue" --> OA
        N6 -- "call limit" --> NE
        OA -- "reply" --> N7
    end

    subgraph COMP["Components - plain Python"]
        PII["logging_utils.py<br/>PII redaction"]
        SAF["safety.py<br/>refusal rules"]
        MEM["memory.py<br/>long-term facts"]
        FB["feedback.py<br/>preference hints"]
        RET["retrieval.py + rag/<br/>semantic search, TF-IDF fallback"]
        TR["tools.py ToolRegistry<br/>order status, eligibility,<br/>escalate_to_human"]
        LLM["llm_client.py<br/>OpenAI live / MockLLM offline"]
    end

    subgraph STORES["Stores"]
        QD[("Qdrant<br/>knowledge base vectors")]
        CP[("Checkpointer<br/>history, last_order_id")]
        LT[("long_term_memory.json")]
        FJ[("feedback.json")]
        LOG[("PII-redacted logs")]
        LS["LangSmith traces<br/>optional, off by default"]
    end

    API --> FA --> N1
    N7 -->|"JSON reply + route + path"| API
    NE -->|"refusal + ticket"| API

    N1 -.-> PII
    N2 -.-> SAF
    N3 -.-> MEM
    N3 -.-> CP
    SUP -.-> FB
    PA -.-> RET
    PA -.-> LLM
    OA -.-> LLM
    N6 -.-> TR
    NE -.-> TR
    N7 -.-> CP
    RET -.-> QD
    MEM -.-> LT
    FB -.-> FJ
    ORCH -.-> LOG
    ORCH -.-> LS
    API -->|"POST /feedback"| FB
```

## 2. How the agents communicate

```mermaid
flowchart LR
    ST[("Shared graph state<br/>route, plan, history,<br/>answer, policy_answer,<br/>sources, tool results, ticket")]
    SUP["Supervisor"] -->|"writes route, plan"| ST
    ST -->|"reads route"| PA["Policy agent"]
    ST -->|"reads route, plan"| OA["Order agent"]
    PA -->|"writes policy_answer, sources"| ST
    OA -->|"writes answer, tool results"| ST
    ST --> FIN["finalize<br/>merges answers"]
```

| Request | `route` | Path through the graph |
|---|---|---|
| "What is your return policy?" | policy | supervisor, policy_agent, finalize |
| "Is order ORD-1002 eligible for a return?" | order | supervisor, order_agent, tools, order_agent, finalize |
| "What is your return policy for order ORD-1002?" | both | supervisor, policy_agent, order_agent, tools, order_agent, finalize (answers merged) |
| "Please process a refund for me right now." | none | safety_check, escalate (no agent runs) |

## 3. One turn in sequence

```mermaid
sequenceDiagram
    actor C as Customer
    participant API as FastAPI /chat
    participant G as Graph
    participant S as safety.py
    participant SUP as Supervisor
    participant PA as Policy agent
    participant OA as Order agent
    participant R as Retrieval
    participant L as LLM
    participant T as ToolRegistry

    C->>API: message + session_id
    API->>G: run_turn (thread_id = session_id)
    G->>G: redact_pii, resolve_memory
    G->>S: safety_check
    alt unsafe request
        G->>T: escalate_to_human
        G-->>API: refusal + ticket (no agent, no LLM)
    else safe request
        G->>SUP: route (order ID? policy words?)
        opt policy or mixed
            SUP->>PA: handle
            PA->>R: search policy text
            R-->>PA: top chunks
            PA->>L: prompt + chunks (no tools)
            L-->>PA: policy answer
        end
        opt order or mixed
            SUP->>OA: handle
            OA->>L: prompt + order tool schemas
            loop until reply or call limit
                L-->>OA: tool call
                OA->>T: execute (allow-listed, capped)
                T-->>OA: result, or ToolError -> ticket
                OA->>L: tool result
            end
            L-->>OA: order answer
        end
        G->>G: finalize (merge, sources, grounding, ticket)
        G-->>API: reply + route + path
    end
    API-->>C: JSON response
```

## 4. Why this shape

- **Least privilege.** The policy agent cannot call tools or see orders; the order agent cannot see
  policy documents. `ToolRegistry.execute(..., allowed=...)` enforces this in code, and a tool call
  from the policy agent escalates to a human.
- **Deterministic supervisor.** Two rules, no LLM call, unit-tested. An LLM router would add latency,
  cost and a misrouting failure mode to the safety-relevant path.
- **Cost.** Single-domain turns use one LLM call. Mixed turns use two.
- **Limit.** Routing keys on an order ID, so an order question with no ID goes to the policy agent,
  which will say it has no documentation and offer a human.

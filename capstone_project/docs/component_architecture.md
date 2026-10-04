# Component Architecture

The system is **one agent** implemented as **one LangGraph workflow**. Components are plain
Python modules that the graph nodes call. The `agents/` folder is a class chain
(`LLMAgent -> RagAgent -> ToolAgent -> FullAgent`) showing how the system was built up in
phases; it is not a set of communicating agents.

## 1. Component view

```mermaid
flowchart LR
    C["Customer"] -->|"POST /chat"| API

    subgraph API_LAYER["API layer - deployment/app.py"]
        API["FastAPI<br/>/chat  /feedback  /health<br/>input validation, request lock"]
    end

    subgraph ORCH["Orchestration - one agent, one workflow"]
        FA["FullAgent facade<br/>agents/full_agent.py"]
        subgraph G["LangGraph StateGraph - graph/app.py"]
            N1["redact_pii"] --> N2{"safety_check"}
            N2 -- "unsafe" --> NE["escalate"]
            N2 -- "safe" --> N3["resolve_memory"]
            N3 --> N4["plan_and_retrieve"]
            N4 --> N5["agent"]
            N5 -- "tool calls" --> N6["tools"]
            N6 -- "continue" --> N5
            N6 -- "call limit" --> NE
            N5 -- "final reply" --> N7["finalize"]
        end
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
    N7 -->|"JSON reply + path"| API
    NE -->|"refusal + ticket"| API

    N1 -.-> PII
    N2 -.-> SAF
    N3 -.-> MEM
    N3 -.-> CP
    N4 -.-> RET
    N4 -.-> FB
    N5 -.-> LLM
    N6 -.-> TR
    NE -.-> TR
    N7 -.-> CP
    RET -.-> QD
    MEM -.-> LT
    FB -.-> FJ
    G -.-> LOG
    G -.-> LS
    API -->|"POST /feedback"| FB
```

## 2. How the pieces communicate in one turn

```mermaid
sequenceDiagram
    actor C as Customer
    participant API as FastAPI /chat
    participant FA as FullAgent
    participant G as Graph nodes
    participant S as safety.py
    participant M as Memory
    participant R as Retrieval
    participant L as LLM
    participant T as ToolRegistry

    C->>API: message + session_id
    API->>FA: run_turn()
    FA->>G: invoke(thread_id = session_id)
    G->>G: redact_pii
    G->>S: safety_check
    alt unsafe request
        G->>T: escalate_to_human
        T-->>G: ticket
        G-->>API: refusal + ticket (LLM never called)
    else safe request
        G->>M: recall last_order_id
        G->>R: search policy text
        R-->>G: top chunks
        G->>L: prompt + chunks + tool schemas
        loop until reply or call limit
            L-->>G: tool call
            G->>T: execute (validated, capped)
            T-->>G: result, or ToolError -> ticket
            G->>L: tool result
        end
        L-->>G: final reply
        G->>G: finalize (sources, grounding, ticket)
        G-->>API: reply + path
    end
    API-->>C: JSON response
```

## 3. Not implemented: what a multi-agent version would look like

Shown for comparison only. The current single-agent design is deliberate: the safety gate is
structural and one workflow is easier to test and explain.

```mermaid
flowchart LR
    U["Customer"] --> SG["Safety gate<br/>deterministic, runs first"]
    SG --> SUP["Supervisor agent<br/>routes the request"]
    SUP --> POL["Policy agent<br/>retrieval only"]
    SUP --> ORD["Order agent<br/>order tools only"]
    SUP --> ESC["Escalation agent<br/>tickets, human handoff"]
    POL --> SUP
    ORD --> SUP
    ESC --> SUP
    SUP --> U
```

Reasons to adopt it later: separate prompts and permissions per specialist (the order agent
never sees policy text), independent evaluation, and independent scaling. Costs: more LLM
calls per turn (latency and cost), more failure modes (routing mistakes, agents disagreeing),
and a harder safety argument.

# CTO Architecture Diagram Prompt

Use the prompt below in ChatGPT to generate a clean architecture diagram for the
Customer Support Agent project presentation.

---

## Prompt to paste into ChatGPT

Create a polished **architecture diagram** for a customer support AI system that I can present to a CTO.

### The most important rule
This system has **exactly ONE request flow** with **one branch point**. Draw **one** main left-to-right pipeline.
- Do **not** draw the FastAPI backend and the agents as separate flows.
- The two specialist agents are **two boxes inside the same workflow container**, drawn as a fork after the supervisor and a merge before the final step. They are **not** two separate pipelines.
- The "offline" vs "live" LLM choice is a **configuration switch** on the LLM, not a separate path.
- "Semantic retrieval with TF-IDF fallback" happens **inside the policy agent box**.
- "Human escalation" is **one box** reached from several earlier steps.

### Context
An AI Support Resolution Agent for retail customer support: policy Q&A (returns, shipping, warranty),
order status and return-eligibility checks, safety refusal of risky requests, and escalation to a human.
A customer message goes through one LangGraph workflow served by a FastAPI endpoint. A deterministic
supervisor routes each request to a **policy agent** or an **order agent** (or both for mixed questions).

### The single flow (draw these boxes in this order, left to right)

1. **Customer** sends a message to
2. **FastAPI `POST /chat`** (validates input, passes `session_id` and message to the workflow), which runs the
3. **Support workflow (LangGraph)** — draw this as ONE large container with these steps inside, in order:
   1. **redact_pii** — masks names, emails, cards, addresses before anything else sees the text
   2. **safety_check** — deterministic refusal rules. **Branch:** if unsafe, go straight to **escalate** (no agent and no LLM runs)
   3. **resolve_memory** — recalls the last order ID and resolves "that order" / "it" (reads the session checkpointer)
   4. **supervisor** — deterministic router (rules, no LLM). Forks to one or both of:
      - **Policy agent** — retrieves policy text (Qdrant semantic search, TF-IDF fallback) and answers with the LLM. **Has no tools and no order data.** If retrieval is weak (below a relevance threshold) it answers "I don't have documentation" **without calling the LLM**, and it cites only relevant documents
      - **Order agent** — LLM plus order tools. **Has no policy documents.** It loops with the **tools** box: order status lookup, return-eligibility check, escalation-ticket creation (arguments validated, allow-listed per agent, maximum 3 calls per turn). If the call limit is hit, go to **escalate**
      - For a mixed question the policy agent runs first, then the order agent
   5. **finalize** — merges the agents' answers, adds source names, labels how the answer is grounded (retrieval, tool result, both, or none), and makes sure any ticket ID appears in the reply
   - **escalate** (one box, reached from safety_check, the tool-call limit, tool failures, and any attempted tool call by the policy agent) — creates a human-handoff ticket
4. The workflow returns a **JSON response** (reply, route, escalated, ticket ID, sources, grounding, path) through FastAPI to the **Customer**.

Show that the agents **communicate only through a shared state box** (route, plan, answers, sources); the agents do not call each other.

### Supporting stores (small boxes attached to the one flow, not separate flows)
- **Knowledge base + Qdrant vector store** — read by the policy agent
- **Session checkpointer** (conversation history, last order ID) — read/written by resolve_memory and finalize
- **Long-term memory file** (non-personal facts) — read/written by resolve_memory
- **Feedback store** — written by `POST /feedback`, read by the supervisor to adapt the prompt
- **PII-redacted logs**
- **Optional LangSmith tracing** (dashed line from the workflow container; off by default)

### Visual style
- Enterprise / CTO presentation quality, clean and simple
- Strict **left-to-right** layout, one main horizontal pipeline
- Use line colors **inside** the single flow:
  - normal answer path (grey or blue)
  - safety / tool-limit refusal path (red) going to the escalate box
  - policy agent in one color, order agent in another, so the fork is easy to read
- Short labels (a few words per box)

### Output format I want
Please return:
1. an **architecture diagram** (image or editable drawing) showing the single flow above
2. a short **executive summary** for the CTO (3-4 sentences)
3. a **legend** explaining the main arrows and colors
4. a version of the diagram optimized for a slide, with shorter labels

---

## Notes for this project
- The project is implemented and runnable; the diagram must reflect the actual system.
- There is one execution path. The same workflow serves the API, the demo, the evaluation, and the CLI.
- Every node writes a session-tagged, PII-redacted log line, and retrieval/vector-store failures are logged
  rather than swallowed. Show "PII-redacted logs" as attached to the whole workflow container.
- Qdrant is reached as a server (Docker Compose) or, if unreachable, as a local on-disk store under `.qdrant/`;
  below that, retrieval falls back to TF-IDF. This is one fallback chain inside the policy agent, not extra flows.

---

## Architecture diagram generation steps

Follow these steps to produce the current diagrams (no code or diagram-as-code format is needed).

### Step 1 - Prepare
1. Open ChatGPT (or any diagram-capable tool) in a new chat.
2. Paste the full prompt from "Prompt to paste into ChatGPT" above, including the "Notes for this project" section.
3. Ask for a slide-ready image or an editable drawing (for example PowerPoint or draw.io style), not code.

### Step 2 - Generate diagram 1: request flow
1. Draw one left-to-right pipeline: Customer -> FastAPI `POST /chat` -> one large "Support workflow (LangGraph)" container -> JSON reply -> Customer.
2. Inside the container, in order: redact_pii -> safety_check -> resolve_memory -> supervisor.
3. Fork after the supervisor into the Policy agent (retrieval + LLM, no tools) and the Order agent (LLM + tools, no documents). Show policy-then-order for mixed questions. Join both at finalize.
4. Add one escalate box. Draw red arrows into it from safety_check (unsafe), the tool-call limit or failure, and a tool call attempted by the policy agent.
5. Colour the policy agent and the order agent differently, and keep the normal path grey or blue.

### Step 3 - Generate diagram 2: supporting stores and observability
1. Attach small boxes to the workflow container, not as separate flows: knowledge base + Qdrant, session checkpointer, long-term memory file, feedback store, PII-redacted logs, and the LLM client.
2. Show the retrieval fallback chain from the policy agent: Qdrant server -> local Qdrant (`.qdrant/`) -> TF-IDF.
3. Show `POST /feedback` writing the feedback store, which the supervisor reads.
4. Add optional LangSmith tracing as a dashed line (off by default), and the MockLLM / OpenAI choice as a config switch on the LLM box.

### Step 4 - Generate diagram 3: deployment view
1. Draw Users -> reverse proxy (TLS, auth, rate limit) -> API container (FastAPI + workflow).
2. Connect the API container to Qdrant (private network), persistent volumes (`state/`, `logs/`, `.qdrant/`), and the optional OpenAI API and LangSmith.

### Step 5 - Review and finish
1. Check that there is exactly one request flow and one fork, and that the agents never call each other (they share state only).
2. Check that every escalation arrow ends at the single escalate box.
3. Ask for the shorter slide version with fewer words per box, plus a 3-4 sentence executive summary and a legend for arrows and colours.
4. Export as PNG or SVG and add it to the slides or to `docs/`.

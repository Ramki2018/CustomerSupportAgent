# CTO Architecture Diagram Prompt

Use the prompt below in ChatGPT to generate a clean architecture diagram for the
Customer Support Agent project presentation.

---

## Prompt to paste into ChatGPT

Create a polished **architecture diagram** for a customer support AI system that I can present to a CTO.

### The most important rule
This system has **exactly ONE request flow**. Draw **one** main left-to-right pipeline, not two.
- Do **not** draw the FastAPI backend and the agent as two separate flows.
- Do **not** draw a separate "FullAgent" or "CLI" flow.
- The "offline" vs "live" LLM choice is a **configuration switch on one box**, not a separate path.
- "Semantic retrieval with TF-IDF fallback" happens **inside one box**, not as a separate path.
- "Human escalation" is **one box** that two different earlier steps can reach.

### Context
An AI Support Resolution Agent for retail customer support. It handles policy Q&A (returns,
shipping, warranty), order status and return-eligibility checks, safety refusal of risky
requests, and escalation to a human. A customer message goes through one LangGraph workflow
served by a FastAPI endpoint.

### The single flow (draw these boxes in this order, left to right)

1. **Customer** sends a message to
2. **FastAPI `POST /chat`** (validates input, passes `session_id` and message to the workflow), which runs the
3. **Support Agent workflow (LangGraph)** — draw this as ONE large container, with these steps inside it, in order:
   1. **redact_pii** — masks names, emails, cards, addresses before anything else sees the text
   2. **safety_check** — deterministic refusal rules. **Branch:** if unsafe, go straight to **escalate** (the LLM is never called)
   3. **resolve_memory** — recalls the last order ID and resolves "that order" / "it" (reads the session checkpointer)
   4. **plan_and_retrieve** — picks the prompt (adapts to feedback), plans the task, and retrieves policy text: Qdrant semantic search, with TF-IDF as fallback
   5. **agent** — the LLM call (OpenAI in live mode, MockLLM in offline mode). **Loop:** if the LLM asks for a tool, go to tools and come back
   6. **tools** — order status lookup, return-eligibility check, escalation-ticket creation; arguments validated, maximum 3 calls per turn. **Branch:** if the call limit is hit, go to **escalate**
   7. **finalize** — adds source names, labels how the answer is grounded (retrieval, tool result, or none), and makes sure any ticket ID appears in the reply
   - **escalate** (one box, reached from safety_check and from the tool-call limit, and used for tool failures) — creates a human-handoff ticket
4. The workflow returns a **JSON response** (reply, escalated, ticket ID, sources, grounding, path) through FastAPI to the **Customer**.

### Supporting stores (draw as small boxes attached to the one flow, not as separate flows)
- **Knowledge base + Qdrant vector store** — read by plan_and_retrieve
- **Session checkpointer** (conversation history, last order ID) — read/written by resolve_memory and finalize
- **Long-term memory file** (non-personal facts) — read/written by resolve_memory
- **Feedback store** — written by `POST /feedback`, read by plan_and_retrieve to adapt the prompt
- **PII-redacted logs**
- **Optional LangSmith tracing** (dashed line from the workflow container; off by default)

### Visual style
- Enterprise / CTO presentation quality, clean and simple
- Strict **left-to-right** layout, one main horizontal pipeline
- Show the three branches clearly **inside** the single flow using different line colors:
  - normal answer path (grey or blue)
  - safety / tool-limit refusal path (red) going to the escalate box
  - retrieval fallback shown as a small note inside plan_and_retrieve, not a separate path
- Short labels (a few words per box)

### Output format I want
Please return:
1. a **Mermaid architecture diagram** showing the single flow above
2. a short **executive summary** for the CTO (3-4 sentences)
3. a **legend** explaining the main arrows and colors
4. a version of the diagram optimized for a slide, with shorter labels

---

## Notes for this project
- The project is implemented and runnable; the diagram must reflect the actual system.
- There is one execution path. The same workflow serves the API, the demo, the evaluation, and the CLI.

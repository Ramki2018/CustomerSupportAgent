# Short Slide-Friendly Prompt

Paste this into ChatGPT to generate a presentation-ready architecture diagram:

---

Create a clean, slide-friendly **architecture diagram** for a customer support AI system.

**Rule: draw exactly ONE left-to-right flow.** Do not draw FastAPI and the agent as two
flows, and do not draw separate offline/online or fallback paths. Offline vs live LLM is a
config switch on one box; retrieval fallback happens inside one box.

### The single flow
Customer → **FastAPI /chat** → **Support Agent (LangGraph workflow)** → JSON reply → Customer

Inside the Support Agent box, in order:
1. **redact_pii** — mask personal data
2. **safety_check** — unsafe → jump to **escalate** (LLM never called)
3. **resolve_memory** — recall order ID, resolve "that order"
4. **plan_and_retrieve** — Qdrant semantic search (TF-IDF fallback), feedback-adapted prompt
5. **agent** — LLM (OpenAI live / MockLLM offline) ⇄ **tools** (order status, return eligibility; max 3 calls)
6. **finalize** — sources, grounding label, ticket named in reply
- **escalate** (one box) — human-handoff ticket; reached from safety_check, the tool-call limit, and tool failures

### Small attached boxes (not separate flows)
Knowledge base + Qdrant · Session memory (checkpointer) · Long-term memory · Feedback store · PII-redacted logs · Optional LangSmith tracing

### Style
- Left-to-right, simple, CTO-friendly, short labels
- Red line for the refusal/escalation branch; one color for the normal path

### Output
Return:
1. a PowerPoint-ready diagram (or Mermaid)
2. a 3-4 sentence executive summary
3. a short legend for the arrows and colors

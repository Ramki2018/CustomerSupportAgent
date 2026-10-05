# Short Slide-Friendly Prompt

Paste this into ChatGPT to generate a presentation-ready architecture diagram:

---

Create a clean, slide-friendly **architecture diagram** for a customer support AI system.

**Rule: draw exactly ONE left-to-right flow with ONE fork.** Do not draw FastAPI and the agents as
separate flows. The two specialist agents are two boxes inside the same workflow container
(fork after the supervisor, merge before finalize). Offline vs live LLM is a config switch on the
LLM; retrieval fallback happens inside the policy agent.

### The single flow
Customer → **FastAPI /chat** → **Support workflow (LangGraph)** → JSON reply → Customer

Inside the workflow box, in order:
1. **redact_pii** — mask personal data
2. **safety_check** — unsafe → jump to **escalate** (no agent, no LLM)
3. **resolve_memory** — recall order ID, resolve "that order"
4. **supervisor** — deterministic router (no LLM), forks to:
   - **Policy agent** — Qdrant semantic search (TF-IDF fallback) + LLM; **no tools**; weak retrieval -> "no documentation" without calling the LLM
   - **Order agent** ⇄ **tools** (order status, return eligibility; allow-listed, max 3 calls) + LLM; **no documents**
   - mixed question: policy agent first, then order agent
5. **finalize** — merge answers, sources, grounding label, ticket named in reply
- **escalate** (one box) — human-handoff ticket; reached from safety_check, the tool-call limit, tool failures, and any tool call attempted by the policy agent

Agents talk only through a **shared state** box; they never call each other.

### Small attached boxes (not separate flows)
Knowledge base + Qdrant · Session memory (checkpointer) · Long-term memory · Feedback store · PII-redacted logs · Optional LangSmith tracing

### Style
- Left-to-right, simple, CTO-friendly, short labels
- Red line for the refusal/escalation branch; one color per agent; one color for the rest

### Output
Return:
1. a PowerPoint-ready diagram (or Mermaid)
2. a 3-4 sentence executive summary
3. a short legend for the arrows and colors

# Short Slide-Friendly Prompt

Paste this into ChatGPT to generate a presentation-ready architecture diagram:

---

Create a clean, slide-friendly **architecture diagram** for a customer support AI system.

### Include these components
- User / Customer
- FastAPI backend
- Safety layer: refusal rules + PII redaction
- Memory layer: session memory + order ID recall
- Retrieval layer: Qdrant semantic search + TF-IDF fallback + knowledge base
- Agent orchestration: planning + tool routing + prompt selection
- Tools: order status, return eligibility, escalation ticket creation
- LLM layer: MockLLM offline mode + OpenAI live mode, orchestrated by a LangGraph workflow (redact → safety → memory → retrieve → agent ⇄ tools → finalize/escalate)
- Storage: logs, feedback, evaluation artifacts

### Show these flows
- User input is sanitized first
- Safety checks run before generation
- Retrieval grounds answers
- Tools handle order status and eligibility
- Unsafe, unresolved, or failed requests escalate to a human agent
- Logs and feedback are recorded after each response

### Style
- Left-to-right flow
- Simple, professional, CTO-friendly
- Clear separation of:
  - offline fallback path
  - semantic retrieval path
  - human escalation path

### Output
Return:
1. a Mermaid diagram
2. a 3–4 sentence executive summary
3. a short legend for the main arrows


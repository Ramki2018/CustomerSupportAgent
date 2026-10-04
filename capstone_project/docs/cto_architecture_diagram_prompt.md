# CTO Architecture Diagram Prompt

Use the prompt below in ChatGPT to generate a clean architecture diagram for the
Customer Support Agent project presentation.

---

## Prompt to paste into ChatGPT

Create a polished **architecture diagram** for a customer support AI system that I can present to a CTO.

### Context
This project is an AI Support Resolution Agent for retail customer support. It handles:
- policy Q&A for returns, shipping, and warranty
- order status and return eligibility checks
- safety refusal for risky requests
- escalation to a human support agent
- logging, feedback, and memory

### Current system components
Please include these major components in the diagram:

1. **User / Customer**
2. **FastAPI Backend**
3. **Safety Layer**
   - policy refusal rules
   - PII redaction
4. **Memory Layer**
   - session memory
   - order ID recall
5. **Retrieval Layer**
   - semantic Qdrant search
   - TF-IDF fallback
   - knowledge base documents
6. **Agent Orchestration**
   - planning
   - tool routing
   - prompt selection
7. **Tools**
   - order status lookup
   - return eligibility check
   - escalation ticket creation
8. **LLM Layer**
   - MockLLM for offline mode
   - OpenAI / LangChain for live mode
9. **Storage / Observability**
   - logs
   - feedback store
   - evaluation artifacts

### Desired diagram style
- Make it **enterprise / CTO presentation quality**
- Use a **clean left-to-right flow**
- Show **inputs, processing layers, and outputs**
- Highlight the difference between:
  - **offline fallback path**
  - **semantic retrieval path**
  - **human escalation path**
- Keep the diagram visually simple but accurate

### Important behaviors to show
- user input is sanitized before memory and retrieval
- safety checks run before LLM generation
- retrieval is used to ground answers
- tools are called for order status and eligibility
- escalation is created when requests are unsafe, unresolved, or tool failures occur
- logs and feedback are recorded after responses

### Output format I want
Please return:
1. a **Mermaid architecture diagram**
2. a short **executive summary** for the CTO
3. a **legend** explaining the main arrows/paths

### Optional enhancement
If helpful, also provide a version of the diagram optimized for a slide deck with shorter labels.

---

## Notes for this project
- The project is already implemented and runnable.
- The diagram should reflect the actual system, not a hypothetical one.
- Prefer concise labels over long explanations inside the diagram.


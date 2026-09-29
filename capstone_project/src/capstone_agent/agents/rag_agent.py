"""Phase 4: adds retrieval-augmented generation (RAG) over the knowledge base."""
from ..logging_utils import log_interaction
from ..retrieval import KnowledgeBase
from ..safety import check as safety_check
from .llm_agent import DEFAULT_VARIANT, PROMPT_VARIANTS, LLMAgent


class RagAgent(LLMAgent):
    def __init__(self, variant: str = DEFAULT_VARIANT):
        super().__init__(variant)
        self.kb = KnowledgeBase()

    def respond(self, session_id: str, message: str, variant: str | None = None, use_retrieval: bool = True) -> str:
        log_interaction(session_id, "user", message)
        decision = safety_check(message)
        if not decision.allowed:
            log_interaction(session_id, "assistant", decision.reason, {"safety_block": True})
            return decision.reason

        system_prompt = PROMPT_VARIANTS[variant or self.variant]
        if use_retrieval:
            results = self.kb.search(message)
            if results:
                context = "\n\n".join(f"[{chunk.doc_id}] {chunk.text}" for _, chunk in results)
                system_prompt += f"\n\nRETRIEVED CONTEXT:\n{context}"
            # If nothing relevant is found, we deliberately do NOT fabricate context —
            # the LLM/MockLLM falls back to "I don't have documentation" + escalation offer.

        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": message}]
        result = self.llm.chat(messages)
        content = result["content"] or ""
        log_interaction(session_id, "assistant", content, {"used_retrieval": use_retrieval})
        return content

    def compare_with_without_retrieval(self, questions: list) -> list:
        rows = []
        for q in questions:
            rows.append({
                "question": q,
                "without_retrieval": self.respond("demo-rag-compare", q, use_retrieval=False),
                "with_retrieval": self.respond("demo-rag-compare", q, use_retrieval=True),
            })
        return rows

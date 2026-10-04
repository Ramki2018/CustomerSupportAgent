"""Phase 6 & 7: planning, memory, and adaptive behaviour on top of ToolAgent.

This is the production agent used for deployment (Phase 8) and evaluation (Phase 9).
"""
import json
import re

from ..feedback import FeedbackStore
from ..logging_utils import get_logger, log_interaction, sanitize_user_message
from ..memory import ConversationMemory
from ..safety import check as safety_check
from ..tools import TOOL_SCHEMAS, ToolError
from .tool_agent import DEFAULT_VARIANT, PROMPT_VARIANTS, ToolAgent

logger = get_logger("full_agent")

# Very small task-decomposition planner for a known multi-step request pattern:
# "check status ... and tell me if I can return it" -> [status lookup, eligibility check]
_MULTI_STEP_PATTERN = re.compile(r"status.*return|return.*status", re.IGNORECASE)
_PRONOUN_REF_PATTERN = re.compile(r"\bit\b|\bthat order\b", re.IGNORECASE)
_ORDER_ID_PATTERN = re.compile(r"ORD-\d{3,}")


class FullAgent(ToolAgent):
    def __init__(self, variant: str = DEFAULT_VARIANT):
        super().__init__(variant)
        self.feedback_store = FeedbackStore()
        self._memories: dict = {}

    def _memory(self, session_id: str) -> ConversationMemory:
        if session_id not in self._memories:
            self._memories[session_id] = ConversationMemory(session_id)
        return self._memories[session_id]

    @staticmethod
    def _plan(message: str) -> list:
        if _MULTI_STEP_PATTERN.search(message):
            return ["get_order_status", "check_return_eligibility"]
        return ["single_step"]

    def handle_message(self, session_id: str, message: str) -> str:
        memory = self._memory(session_id)
        safe_message = sanitize_user_message(message)
        memory.add_turn("user", safe_message)
        log_interaction(session_id, "user", safe_message)

        decision = safety_check(safe_message)
        if not decision.allowed:
            if decision.escalate:
                self.tool_registry.execute(
                    "escalate_to_human", {"reason": safe_message[:120], "session_id": session_id}, 0
                )
            memory.add_turn("assistant", decision.reason)
            log_interaction(session_id, "assistant", decision.reason, {"safety_block": True})
            return decision.reason

        # Memory: remember the last order ID mentioned, and resolve pronoun references
        # ("that order" / "it") to it in later turns within the same session.
        order_match = _ORDER_ID_PATTERN.search(safe_message)
        if order_match:
            memory.remember("last_order_id", order_match.group(0))
        elif memory.recall("last_order_id") and _PRONOUN_REF_PATTERN.search(safe_message):
            resolved = f"{safe_message} (referring to order {memory.recall('last_order_id')})"
            memory.short_term[-1]["content"] = resolved
            safe_message = resolved

        # Adaptive behaviour: shift prompt strategy based on recent user feedback.
        hints = self.feedback_store.preference_hints()
        variant = "v3_role_constraints_concise" if hints.get("prefer_concise") else self.variant

        plan = self._plan(safe_message)
        system_prompt = PROMPT_VARIANTS[variant] + f"\n\nPLAN: {plan}"
        results = self.kb.search(safe_message)
        if results:
            context = "\n\n".join(f"[{c.doc_id}] {c.text}" for _, c in results)
            system_prompt += f"\n\nRETRIEVED CONTEXT:\n{context}"

        messages = [{"role": "system", "content": system_prompt}, *memory.get_recent_context()]

        call_count = 0
        while True:
            result = self.llm.chat(messages, tools=TOOL_SCHEMAS)
            tool_calls = result.get("tool_calls")
            if not tool_calls:
                content = result["content"] or ""
                # If retrieval provided context, append concise provenance to the reply
                try:
                    if results:
                        doc_ids = [c.doc_id for _, c in results]
                        unique_ids = sorted(set(doc_ids))
                        if unique_ids:
                            provenance = "\n\nSources: " + ", ".join(unique_ids)
                            content = content + provenance
                except Exception:
                    # Best-effort provenance; do not fail the response if something goes wrong
                    pass
                memory.add_turn("assistant", content)
                log_interaction(session_id, "assistant", content, {"plan": plan, "prompt_variant": variant})
                return content

            for call in tool_calls:
                name = call["function"]["name"]
                try:
                    arguments = json.loads(call["function"]["arguments"])
                except json.JSONDecodeError:
                    arguments = {}
                try:
                    tool_result = self.tool_registry.execute(name, arguments, call_count)
                except ToolError as exc:
                    tool_result = {"error": str(exc)}
                call_count += 1
                messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
                messages.append({"role": "tool", "name": name, "content": json.dumps(tool_result)})

            if call_count >= self.tool_registry.max_calls_per_turn:
                fallback = "I'm having trouble resolving this automatically. Escalating to a human agent."
                memory.add_turn("assistant", fallback)
                log_interaction(session_id, "assistant", fallback, {"loop_guard": True})
                return fallback

    def record_feedback(self, session_id: str, rating: int, comment: str = "") -> None:
        self.feedback_store.add(session_id, rating, comment)

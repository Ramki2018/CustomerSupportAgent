"""Phase 5: adds tool usage (function calling) with safeguards.

Safeguards demonstrated:
  - `ToolRegistry.max_calls_per_turn` prevents infinite tool-call loops.
  - Unknown-order / invalid-argument calls raise `ToolError`, handled gracefully
    (see demo/run_demo.py interaction 4 for a real failed-tool-call example).
"""
import json

from ..logging_utils import get_logger, log_interaction
from ..safety import check as safety_check
from ..tools import TOOL_SCHEMAS, ToolError, ToolRegistry
from .rag_agent import DEFAULT_VARIANT, PROMPT_VARIANTS, RagAgent

logger = get_logger("tool_agent")


class ToolAgent(RagAgent):
    def __init__(self, variant: str = DEFAULT_VARIANT):
        super().__init__(variant)
        self.tool_registry = ToolRegistry()

    def respond(self, session_id: str, message: str, variant: str | None = None) -> str:
        log_interaction(session_id, "user", message)
        decision = safety_check(message)
        if not decision.allowed:
            if decision.escalate:
                self.tool_registry.execute(
                    "escalate_to_human", {"reason": message[:120], "session_id": session_id}, 0
                )
            log_interaction(session_id, "assistant", decision.reason, {"safety_block": True})
            return decision.reason

        system_prompt = PROMPT_VARIANTS[variant or self.variant]
        results = self.kb.search(message)
        if results:
            context = "\n\n".join(f"[{c.doc_id}] {c.text}" for _, c in results)
            system_prompt += f"\n\nRETRIEVED CONTEXT:\n{context}"
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": message}]

        call_count = 0
        while True:
            result = self.llm.chat(messages, tools=TOOL_SCHEMAS)
            tool_calls = result.get("tool_calls")
            if not tool_calls:
                content = result["content"] or ""
                log_interaction(session_id, "assistant", content, {"tool_calls_made": call_count})
                return content

            for call in tool_calls:
                name = call["function"]["name"]
                try:
                    arguments = json.loads(call["function"]["arguments"])
                except json.JSONDecodeError:
                    arguments = {}
                try:
                    tool_result = self.tool_registry.execute(name, arguments, call_count)
                    logger.info(f"Tool '{name}' called with {arguments} -> {tool_result}")
                except ToolError as exc:
                    tool_result = {"error": str(exc)}
                    logger.warning(f"Tool call failed/blocked: {name}({arguments}) -> {exc}")
                call_count += 1
                messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
                messages.append({"role": "tool", "name": name, "content": json.dumps(tool_result)})

            if call_count >= self.tool_registry.max_calls_per_turn:
                fallback = "I'm having trouble resolving this automatically. Escalating to a human agent."
                log_interaction(session_id, "assistant", fallback, {"tool_calls_made": call_count, "loop_guard": True})
                return fallback

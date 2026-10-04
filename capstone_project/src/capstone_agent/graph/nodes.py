"""Node implementations for the support-agent LangGraph workflow.

Nodes are bound to a `FullAgent` instance (its LLM client, knowledge base, tool
registry, and feedback store) and read those attributes at call time. Each node
returns only the fields it owns, and appends its name to `trace` so every turn
records the exact path it took.

Safety decisions (`safety_check`, loop guard, tool validation) are plain Python;
the LLM is only reachable through the `agent` node, after the safety gate.
"""

from __future__ import annotations

import json
import re

from ..agents.llm_agent import PROMPT_VARIANTS
from ..logging_utils import get_logger, log_interaction, sanitize_user_message
from ..safety import check as safety_check
from ..tools import TOOL_REGISTRY, TOOL_SCHEMAS, ToolError
from .state import SupportState

logger = get_logger("support_graph")

# Very small task-decomposition planner for a known multi-step request pattern:
# "check status ... and tell me if I can return it" -> [status lookup, eligibility check]
_MULTI_STEP_PATTERN = re.compile(r"status.*return|return.*status", re.IGNORECASE)
_PRONOUN_REF_PATTERN = re.compile(r"\bit\b|\bthat order\b", re.IGNORECASE)
_ORDER_ID_PATTERN = re.compile(r"ORD-\d{3,}")

LOOP_GUARD_REPLY = "I'm having trouble resolving this automatically. I've escalated it to a human agent."
CONCISE_VARIANT = "v3_role_constraints_concise"


def plan_for(message: str) -> list[str]:
    if _MULTI_STEP_PATTERN.search(message):
        return ["get_order_status", "check_return_eligibility"]
    return ["single_step"]


def _trace(state: SupportState, name: str) -> list[str]:
    return [*state.get("trace", []), name]


class SupportNodes:
    def __init__(self, agent):
        self.agent = agent

    def redact_pii(self, state: SupportState) -> SupportState:
        """Redact PII and reset all per-turn fields (state carries over between turns)."""
        sanitized = sanitize_user_message(state.get("user_message", ""))
        log_interaction(state["session_id"], "user", sanitized)
        return {
            "sanitized_message": sanitized,
            "is_safe": True,
            "safety_reason": "",
            "plan": [],
            "prompt_variant": "",
            "retrieved": [],
            "sources": [],
            "messages": [],
            "pending_tool_calls": [],
            "tool_calls_made": 0,
            "needs_ticket": False,
            "escalation_reason": "",
            "escalated": False,
            "ticket_id": "",
            "user_turn_recorded": False,
            "answer": "",
            "grounding": "",
            "trace": ["redact_pii"],
        }

    def safety_check(self, state: SupportState) -> SupportState:
        decision = safety_check(state["sanitized_message"])
        update: SupportState = {"is_safe": decision.allowed, "trace": _trace(state, "safety_check")}
        if not decision.allowed:
            update.update(
                answer=decision.reason,
                safety_reason=decision.reason,
                needs_ticket=decision.escalate,
                escalation_reason=state["sanitized_message"][:120],
            )
        return update

    def resolve_memory(self, state: SupportState) -> SupportState:
        """Remember the last order ID and resolve pronoun references ("that order") to it."""
        message = state["sanitized_message"]
        memory = self.agent._memory(state["session_id"])
        last_order_id = state.get("last_order_id")

        order_match = _ORDER_ID_PATTERN.search(message)
        if order_match:
            last_order_id = order_match.group(0)
            memory.remember("last_order_id", last_order_id)
        else:
            # Falls back to long-term memory so the fact survives process restarts.
            last_order_id = last_order_id or memory.recall("last_order_id")
            if last_order_id and _PRONOUN_REF_PATTERN.search(message):
                message = f"{message} (referring to order {last_order_id})"

        update: SupportState = {
            "sanitized_message": message,
            "history": [{"role": "user", "content": message}],
            "user_turn_recorded": True,
            "trace": _trace(state, "resolve_memory"),
        }
        if last_order_id:
            update["last_order_id"] = last_order_id
        return update

    def plan_and_retrieve(self, state: SupportState) -> SupportState:
        """Adapt the prompt to feedback, plan the task, and ground the prompt in retrieval."""
        message = state["sanitized_message"]
        hints = self.agent.feedback_store.preference_hints()
        variant = CONCISE_VARIANT if hints.get("prefer_concise") else self.agent.variant

        plan = plan_for(message)
        system_prompt = PROMPT_VARIANTS[variant] + f"\n\nPLAN: {plan}"

        retrieved = [
            {"doc_id": chunk.doc_id, "text": chunk.text, "score": float(score)}
            for score, chunk in self.agent.kb.search(message)
        ]
        if retrieved:
            context = "\n\n".join(f"[{r['doc_id']}] {r['text']}" for r in retrieved)
            system_prompt += f"\n\nRETRIEVED CONTEXT:\n{context}"

        return {
            "plan": plan,
            "prompt_variant": variant,
            "retrieved": retrieved,
            "sources": sorted({r["doc_id"] for r in retrieved}),
            "messages": [{"role": "system", "content": system_prompt}, *state.get("history", [])],
            "trace": _trace(state, "plan_and_retrieve"),
        }

    def call_llm(self, state: SupportState) -> SupportState:
        result = self.agent.llm.chat(state["messages"], tools=TOOL_SCHEMAS)
        tool_calls = result.get("tool_calls")
        if tool_calls:
            return {"pending_tool_calls": tool_calls, "trace": _trace(state, "agent")}
        return {"answer": result["content"] or "", "pending_tool_calls": [], "trace": _trace(state, "agent")}

    def run_tools(self, state: SupportState) -> SupportState:
        """Execute pending tool calls through the guarded ToolRegistry."""
        registry = self.agent.tool_registry
        session_id = state["session_id"]
        messages = list(state["messages"])
        count = state.get("tool_calls_made", 0)
        escalated = state.get("escalated", False)
        ticket_id = state.get("ticket_id", "")

        for call in state.get("pending_tool_calls", []):
            name = call["function"]["name"]
            try:
                arguments = json.loads(call["function"]["arguments"])
            except json.JSONDecodeError:
                arguments = {}
            try:
                tool_result = registry.execute(name, arguments, count)
                logger.info(f"Tool '{name}' called with {arguments} -> {tool_result}")
                if name == "escalate_to_human":
                    escalated, ticket_id = True, tool_result.get("ticket_id", ticket_id)
            except ToolError as exc:
                logger.warning(f"Tool call failed/blocked: {name}({arguments}) -> {exc}")
                tool_result = TOOL_REGISTRY["escalate_to_human"](reason=f"{name}: {exc}", session_id=session_id)
                escalated, ticket_id = True, tool_result["ticket_id"]
            count += 1
            messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
            messages.append(
                {"role": "tool", "tool_call_id": call.get("id"), "name": name, "content": json.dumps(tool_result)}
            )

        update: SupportState = {
            "messages": messages,
            "pending_tool_calls": [],
            "tool_calls_made": count,
            "escalated": escalated,
            "ticket_id": ticket_id,
            "trace": _trace(state, "tools"),
        }
        if count >= registry.max_calls_per_turn:
            update.update(answer=LOOP_GUARD_REPLY, needs_ticket=True, escalation_reason="tool loop guard reached")
        return update

    def escalate(self, state: SupportState) -> SupportState:
        """Create the human-handoff ticket and record the refusal/guard reply."""
        session_id = state["session_id"]
        ticket_id = state.get("ticket_id", "")
        if state.get("needs_ticket"):
            ticket = TOOL_REGISTRY["escalate_to_human"](
                reason=state.get("escalation_reason", "escalated"), session_id=session_id
            )
            ticket_id = ticket["ticket_id"]

        answer = state.get("answer", "")
        turns = [] if state.get("user_turn_recorded") else [{"role": "user", "content": state["sanitized_message"]}]
        turns.append({"role": "assistant", "content": answer})
        extra = {"safety_block": True} if state.get("safety_reason") else {"loop_guard": True}
        log_interaction(session_id, "assistant", answer, {**extra, "ticket_id": ticket_id})
        return {
            "escalated": bool(ticket_id),
            "ticket_id": ticket_id,
            "history": turns,
            "grounding": "none",
            "trace": _trace(state, "escalate"),
        }

    def finalize(self, state: SupportState) -> SupportState:
        """Attach provenance, label how the reply is grounded, and record the turn."""
        content = state.get("answer", "")
        used_tools = bool(state.get("tool_calls_made"))
        # Tool-grounded replies come from the order system, so retrieved policy docs are not their source.
        sources = [] if used_tools else state.get("sources", [])
        if sources:
            content += "\n\nSources: " + ", ".join(sources)

        # The reply must match the actual handoff state, whatever wording the model chose.
        ticket_id = state.get("ticket_id", "")
        if state.get("escalated") and ticket_id and ticket_id not in content:
            content += f"\n\nI've created ticket {ticket_id} so a human agent can follow up."

        if used_tools:
            grounding = "tool_result"
        elif sources:
            grounding = "retrieval"
        else:
            grounding = "none"

        trace = _trace(state, "finalize")
        log_interaction(
            state["session_id"],
            "assistant",
            content,
            {"plan": state.get("plan"), "prompt_variant": state.get("prompt_variant"), "grounding": grounding, "path": trace},
        )
        return {
            "answer": content,
            "sources": sources,
            "grounding": grounding,
            "history": [{"role": "assistant", "content": content}],
            "trace": trace,
        }

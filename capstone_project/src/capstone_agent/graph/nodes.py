"""Node implementations for the support-agent LangGraph workflow.

Nodes are bound to a `FullAgent` instance (its LLM client, knowledge base, tool
registry, and feedback store) and read those attributes at call time. Each node
returns only the fields it owns, and appends its name to `trace` so every turn
records the exact path it took.

Roles:
  - `supervisor`    deterministic router (no LLM): order agent if an order ID is present,
                    otherwise policy agent
  - `policy_agent`  retrieval + LLM, with NO tools and no access to order data
  - `order_agent`   LLM + order tools, with NO policy documents
Agents communicate only through shared graph state (`route`, `plan`, `answer`,
`sources`); neither calls the other.

Safety decisions (`safety_check`, tool permissions, loop guard, tool validation) are plain
Python; the LLM is only reachable through a specialist agent, after the safety gate.
"""

from __future__ import annotations

import json
import re

from ..agents.llm_agent import PROMPT_VARIANTS
from ..logging_utils import get_logger, log_interaction, sanitize_user_message
from ..safety import check as safety_check
from ..tools import ORDER_AGENT_TOOL_SCHEMAS, ORDER_AGENT_TOOLS, TOOL_REGISTRY, ToolError
from .state import SupportState

logger = get_logger("support_graph")

# Very small task-decomposition planner for a known multi-step request pattern:
# "check status ... and tell me if I can return it" -> [status lookup, eligibility check]
_MULTI_STEP_PATTERN = re.compile(r"status.*return|return.*status", re.IGNORECASE)
_PRONOUN_REF_PATTERN = re.compile(r"\bit\b|\bthat order\b", re.IGNORECASE)
_ORDER_ID_PATTERN = re.compile(r"ORD-\d{3,}")
_POLICY_WORDS_PATTERN = re.compile(r"\bpolic(?:y|ies)\b|\bwarranty\b|\bprice[- ]?match", re.IGNORECASE)
_MODEL_SOURCES_LINE = re.compile(r"\s*Sources?:[^\n]*\s*$", re.IGNORECASE)

LOOP_GUARD_REPLY = "I'm having trouble resolving this automatically. I've escalated it to a human agent."
CONCISE_VARIANT = "v3_role_constraints_concise"

POLICY_ROLE = (
    "ROLE: policy agent. Answer only from the retrieved policy context below. "
    "You cannot look up orders or take actions."
)
ORDER_ROLE = (
    "ROLE: order agent. Use the order tools to answer. You have no policy documents, "
    "so do not state store policy beyond what a tool result contains."
)


def plan_for(message: str) -> list[str]:
    if _MULTI_STEP_PATTERN.search(message):
        return ["get_order_status", "check_return_eligibility"]
    return ["single_step"]


def route_for(message: str) -> str:
    """Deterministic supervisor rule.

    An order ID (typed or resolved from memory) means order work; explicit policy wording as
    well means a mixed request, so both specialists answer and their replies are merged.
    """
    if not _ORDER_ID_PATTERN.search(message):
        return "policy"
    return "both" if _POLICY_WORDS_PATTERN.search(message) else "order"


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
            "route": "",
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

    def supervisor(self, state: SupportState) -> SupportState:
        """Route the request to a specialist agent. Deterministic rules, no LLM call."""
        message = state["sanitized_message"]
        hints = self.agent.feedback_store.preference_hints()
        variant = CONCISE_VARIANT if hints.get("prefer_concise") else self.agent.variant
        return {
            "plan": plan_for(message),
            "prompt_variant": variant,
            "route": route_for(message),
            "trace": _trace(state, "supervisor"),
        }

    def policy_agent(self, state: SupportState) -> SupportState:
        """Answer policy questions from retrieved documents. Has no tools and no order access."""
        message = state["sanitized_message"]
        retrieved = [
            {"doc_id": chunk.doc_id, "text": chunk.text, "score": float(score)}
            for score, chunk in self.agent.kb.search(message)
        ]
        system_prompt = PROMPT_VARIANTS[state["prompt_variant"]] + f"\n\n{POLICY_ROLE}"
        if retrieved:
            context = "\n\n".join(f"[{r['doc_id']}] {r['text']}" for r in retrieved)
            system_prompt += f"\n\nRETRIEVED CONTEXT:\n{context}"
        messages = [{"role": "system", "content": system_prompt}, *state.get("history", [])]

        result = self.agent.llm.chat(messages, tools=None)
        update: SupportState = {
            "retrieved": retrieved,
            "sources": sorted({r["doc_id"] for r in retrieved}),
            "trace": _trace(state, "policy_agent"),
        }
        if result.get("tool_calls"):
            # This agent holds no tools, so a tool call is a violation: hand off to a human.
            logger.warning("Policy agent attempted a tool call; escalating")
            update.update(answer=LOOP_GUARD_REPLY, needs_ticket=True, escalation_reason="policy agent attempted a tool call")
        else:
            answer = result["content"] or ""
            # For a mixed request the order agent runs next; keep this part for the merge in finalize.
            update.update(answer=answer, policy_answer=answer)
        return update

    def order_agent(self, state: SupportState) -> SupportState:
        """Handle order questions with the order tools. Sees no policy documents."""
        messages = state.get("messages") or []
        if not messages:
            system_prompt = (
                PROMPT_VARIANTS[state["prompt_variant"]] + f"\n\n{ORDER_ROLE}\n\nPLAN: {state.get('plan', [])}"
            )
            messages = [{"role": "system", "content": system_prompt}, *state.get("history", [])]

        result = self.agent.llm.chat(messages, tools=ORDER_AGENT_TOOL_SCHEMAS)
        update: SupportState = {"messages": messages, "trace": _trace(state, "order_agent")}
        tool_calls = result.get("tool_calls")
        if tool_calls:
            update["pending_tool_calls"] = tool_calls
        else:
            update.update(answer=result["content"] or "", pending_tool_calls=[])
        return update

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
                if name == "escalate_to_human" and ticket_id:
                    # One handoff per turn: a second request returns the existing ticket.
                    tool_result = {"ticket_id": ticket_id, "status": "already_queued_for_human_review"}
                else:
                    tool_result = registry.execute(name, arguments, count, allowed=ORDER_AGENT_TOOLS)
                    if name == "escalate_to_human":
                        escalated, ticket_id = True, tool_result.get("ticket_id", ticket_id)
                logger.info(f"Tool '{name}' called with {arguments} -> {tool_result}")
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
        """Merge specialist answers, attach provenance, label grounding, and record the turn."""
        content = state.get("answer", "")
        used_tools = bool(state.get("tool_calls_made"))
        policy_answer = state.get("policy_answer", "")
        if state.get("route") == "both" and policy_answer:
            # Mixed request: order agent's answer first, then the policy agent's, no extra LLM call.
            content = f"{content}\n\n{policy_answer}"
        # Only the policy agent retrieves documents, so `sources` is empty for order-only turns.
        sources = state.get("sources", [])
        if sources:
            # Drop a trailing "Sources: ..." line the model may have written itself; ours is authoritative.
            content = _MODEL_SOURCES_LINE.sub("", content)
            content += "\n\nSources: " + ", ".join(sources)

        # The reply must match the actual handoff state, whatever wording the model chose.
        ticket_id = state.get("ticket_id", "")
        if state.get("escalated") and ticket_id and ticket_id not in content:
            content += f"\n\nI've created ticket {ticket_id} so a human agent can follow up."

        if used_tools and sources:
            grounding = "tool_result+retrieval"
        elif used_tools:
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

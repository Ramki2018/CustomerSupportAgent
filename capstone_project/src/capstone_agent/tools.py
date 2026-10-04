"""Agent tools with schemas, validation, and safeguards (Phase 5).

Business-rule decisions (return eligibility) are deterministic plain Python,
not LLM judgment, so they are auditable, testable, and reproducible.
"""
from datetime import date
from typing import Callable

from . import config
from .logging_utils import get_logger
from .mock_data import ORDERS

logger = get_logger("tools")


class ToolError(Exception):
    pass


def tool_order_status(order_id: str) -> dict:
    order = ORDERS.get(order_id)
    if not order:
        raise ToolError(f"No order found with id {order_id}.")
    return dict(order)


def _return_eligibility_logic(order: dict, use_delivered_date: bool) -> dict:
    """`use_delivered_date=False` reproduces a real bug found during Phase 9
    evaluation: the return window was measured from `order_date` instead of
    `delivered_date`, which understates eligibility for slow-shipping orders.
    The fixed/default behaviour uses `delivered_date` (see tests/test_tools.py
    and docs/03_evaluation_report.md for the before/after proof).
    """
    if order["status"] != "delivered":
        return {"eligible": False, "reason": "Item has not been delivered yet."}
    reference_field = "delivered_date" if use_delivered_date else "order_date"
    reference_date = date.fromisoformat(order[reference_field])
    days_elapsed = (date.today() - reference_date).days
    eligible = days_elapsed <= config.RETURN_WINDOW_DAYS
    return {
        "eligible": eligible,
        "days_elapsed": days_elapsed,
        "window_days": config.RETURN_WINDOW_DAYS,
        "measured_from": reference_field,
    }


def tool_check_return_eligibility(order_id: str, _use_delivered_date: bool = True) -> dict:
    order = ORDERS.get(order_id)
    if not order:
        raise ToolError(f"No order found with id {order_id}.")
    return _return_eligibility_logic(order, use_delivered_date=_use_delivered_date)


def tool_escalate_to_human(reason: str, session_id: str) -> dict:
    ticket_id = f"ESC-{abs(hash((session_id, reason))) % 100000:05d}"
    logger.info(f"Escalation created {ticket_id} for session {session_id}: {reason}")
    return {"ticket_id": ticket_id, "status": "queued_for_human_review", "reason": reason}


TOOL_REGISTRY: dict[str, Callable] = {
    "get_order_status": tool_order_status,
    "check_return_eligibility": tool_check_return_eligibility,
    "escalate_to_human": tool_escalate_to_human,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": "Look up the shipping/delivery status of a customer order by order ID.",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string", "description": "Order ID, e.g. ORD-1001"}},
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_return_eligibility",
            "description": "Check whether an order is still within the return window.",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": "Escalate the conversation to a human support agent.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}, "session_id": {"type": "string"}},
                "required": ["reason", "session_id"],
            },
        },
    },
]

# Per-agent tool permissions. The policy agent gets no tools; the order agent gets the
# order tools plus the escalation hand-off. Enforced by ToolRegistry.execute(allowed=...).
ORDER_AGENT_TOOLS = frozenset({"get_order_status", "check_return_eligibility", "escalate_to_human"})
ORDER_AGENT_TOOL_SCHEMAS = [s for s in TOOL_SCHEMAS if s["function"]["name"] in ORDER_AGENT_TOOLS]


class ToolRegistry:
    """Executes tool calls with loop-prevention, argument-validation, and permission safeguards."""

    def __init__(self, max_calls_per_turn: int = config.MAX_TOOL_CALLS_PER_TURN):
        self.max_calls_per_turn = max_calls_per_turn

    def execute(self, name: str, arguments: dict, call_count: int, allowed: frozenset | set | None = None) -> dict:
        """Run a tool. `allowed` is the calling agent's allow-list; None means unrestricted."""
        if call_count >= self.max_calls_per_turn:
            raise ToolError(f"Tool call limit ({self.max_calls_per_turn}) reached for this turn; escalating instead.")
        if name not in TOOL_REGISTRY:
            raise ToolError(f"Unknown tool '{name}'.")
        if allowed is not None and name not in allowed:
            raise ToolError(f"Tool '{name}' is not permitted for this agent.")
        try:
            return TOOL_REGISTRY[name](**arguments)
        except TypeError as exc:
            raise ToolError(f"Invalid arguments for tool '{name}': {exc}") from exc

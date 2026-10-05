"""Conditional routing helpers for the support-agent graph.

Pure functions of state, so every branch decision is deterministic, unit-testable,
and visible in the LangSmith trace.
"""

from __future__ import annotations

from typing import Literal

from .state import SupportState


def route_after_safety(state: SupportState) -> Literal["escalate", "resolve_memory"]:
    """Unsafe requests go straight to escalation; the LLM is never called for them."""
    return "resolve_memory" if state.get("is_safe", True) else "escalate"


def route_to_specialist(state: SupportState) -> Literal["order_agent", "policy_agent"]:
    """The supervisor's decision, read from state. Pure and deterministic (no LLM).

    Mixed requests ("both") start with the policy agent, then continue to the order agent.
    """
    return "order_agent" if state.get("route") == "order" else "policy_agent"


def route_after_policy_agent(state: SupportState) -> Literal["escalate", "order_agent", "finalize"]:
    """The policy agent has no tools; an attempted tool call is a violation and escalates."""
    if state.get("needs_ticket"):
        return "escalate"
    return "order_agent" if state.get("route") == "both" else "finalize"


def route_after_order_agent(state: SupportState) -> Literal["tools", "finalize"]:
    return "tools" if state.get("pending_tool_calls") else "finalize"


def route_after_tools(state: SupportState) -> Literal["escalate", "order_agent"]:
    """The tool loop guard sets `needs_ticket`; otherwise return to the order agent."""
    return "escalate" if state.get("needs_ticket") else "order_agent"

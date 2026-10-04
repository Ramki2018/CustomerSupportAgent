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


def route_after_agent(state: SupportState) -> Literal["tools", "finalize"]:
    return "tools" if state.get("pending_tool_calls") else "finalize"


def route_after_tools(state: SupportState) -> Literal["escalate", "agent"]:
    """The tool loop guard sets `needs_ticket`; otherwise return to the agent."""
    return "escalate" if state.get("needs_ticket") else "agent"

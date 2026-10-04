"""Conditional routing helpers for the LangGraph workflow.

These functions map graph state to the next node name. They are intentionally
small and deterministic so the graph is easy to inspect and debug.
"""

from __future__ import annotations

from typing import Literal

from .state import AgentState

RouteName = Literal["refuse", "retrieve", "escalate", "generate"]


def route_after_safety(state: AgentState) -> RouteName:
    if not state["is_safe"]:
        return "refuse"
    return "retrieve"


def route_after_verification(state: AgentState) -> RouteName:
    if state["verification_result"]["needs_escalation"] or state.get("escalate"):
        return "escalate"
    return "generate"

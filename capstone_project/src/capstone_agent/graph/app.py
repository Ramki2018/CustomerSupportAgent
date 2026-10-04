"""LangGraph application entrypoint.

This module prefers a real LangGraph `StateGraph` when the dependency is
installed. If LangGraph is unavailable, it falls back to the existing
lightweight runner so the capstone demo remains deployable and rollback-safe.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

if not os.getenv("LANGCHAIN_API_KEY"):
    os.environ["LANGCHAIN_TRACING_V2"] = "false"

from .nodes import (
    answer_generation_node,
    escalation_node,
    evidence_verify_node,
    pii_redact_node,
    retrieval_node,
    safety_check_node,
)
from .routing import route_after_safety, route_after_verification
from .state import AgentState

try:  # pragma: no cover - exercised only when langgraph is installed
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover - fallback path is the default in CI
    END = "__end__"
    StateGraph = None


@dataclass
class FallbackSupportGraph:
    """Lightweight runner that mirrors the LangGraph execution shape."""

    def invoke(self, initial_state: AgentState) -> AgentState:
        state: AgentState = {
            **initial_state,
            "metadata": dict(initial_state.get("metadata") or {}),
        }

        state.update(pii_redact_node(state))
        state.update(safety_check_node(state))

        safety_route = route_after_safety(state)
        if safety_route == "refuse":
            state.update(escalation_node(state))
            state["metadata"]["route"] = "refuse"
            return state

        if safety_route != "retrieve":
            state.update(escalation_node(state))
            state["metadata"]["route"] = safety_route
            return state

        state.update(retrieval_node(state))
        state.update(evidence_verify_node(state))

        verification_route = route_after_verification(state)
        state["metadata"]["route"] = verification_route
        if verification_route == "escalate":
            state.update(escalation_node(state))
            return state

        state.update(answer_generation_node(state))
        return state


def _build_real_stategraph() -> Any:
    graph = StateGraph(AgentState)
    graph.add_node("pii_redact", pii_redact_node)
    graph.add_node("safety_check", safety_check_node)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("evidence_verify", evidence_verify_node)
    graph.add_node("answer_generation", answer_generation_node)
    graph.add_node("escalation", escalation_node)

    graph.set_entry_point("pii_redact")
    graph.add_edge("pii_redact", "safety_check")
    graph.add_conditional_edges(
        "safety_check",
        route_after_safety,
        {
            "refuse": "escalation",
            "retrieve": "retrieval",
        },
    )
    graph.add_edge("retrieval", "evidence_verify")
    graph.add_conditional_edges(
        "evidence_verify",
        route_after_verification,
        {
            "escalate": "escalation",
            "generate": "answer_generation",
        },
    )
    graph.add_edge("answer_generation", END)
    graph.add_edge("escalation", END)
    return graph.compile()


def build_graph() -> Any:
    """Return a graph object with an `invoke(initial_state)` API.

    If LangGraph is installed and not explicitly disabled, returns a compiled
    `StateGraph`. Otherwise, falls back to the lightweight runner.
    """
    use_real = os.getenv("USE_REAL_LANGGRAPH", "true").lower() == "true"
    if use_real and StateGraph is not None:
        return _build_real_stategraph()
    return FallbackSupportGraph()


__all__ = ["FallbackSupportGraph", "build_graph"]

"""LangGraph workflow for the support agents.

    START -> redact_pii -> safety_check --(unsafe)--> escalate -> END
                               |
                          (safe) v
                        resolve_memory -> supervisor --(no order ID)--> policy_agent --> finalize -> END
                                              |                              |(tool call attempted)
                                       (order ID)                            v
                                              v                          escalate -> END
                                        order_agent <--(continue)-- tools
                                          |  (tool calls) --------->   |
                                          v (reply)                    +--(call limit)--> escalate
                                       finalize -> END

The supervisor is deterministic (no LLM). The policy agent has retrieval and no tools; the
order agent has the order tools and no documents. Agents communicate through graph state only.
Every node is traced by LangSmith when tracing is enabled (see `config.py`).
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import SupportNodes
from .routing import (
    route_after_order_agent,
    route_after_policy_agent,
    route_after_safety,
    route_after_tools,
    route_to_specialist,
)
from .state import SupportState


def build_support_graph(agent, checkpointer=None):
    """Compile the workflow for `agent` (a FullAgent).

    Pass a checkpointer (e.g. `MemorySaver()`) for local runs so `history` and
    `last_order_id` persist per `thread_id`. Omit it when a hosting platform
    (LangGraph Platform / LangSmith Deployments) supplies persistence itself.
    """
    nodes = SupportNodes(agent)
    graph = StateGraph(SupportState)

    graph.add_node("redact_pii", nodes.redact_pii)
    graph.add_node("safety_check", nodes.safety_check)
    graph.add_node("resolve_memory", nodes.resolve_memory)
    graph.add_node("supervisor", nodes.supervisor)
    graph.add_node("policy_agent", nodes.policy_agent)
    graph.add_node("order_agent", nodes.order_agent)
    graph.add_node("tools", nodes.run_tools)
    graph.add_node("escalate", nodes.escalate)
    graph.add_node("finalize", nodes.finalize)

    graph.add_edge(START, "redact_pii")
    graph.add_edge("redact_pii", "safety_check")
    graph.add_conditional_edges(
        "safety_check", route_after_safety, {"escalate": "escalate", "resolve_memory": "resolve_memory"}
    )
    graph.add_edge("resolve_memory", "supervisor")
    graph.add_conditional_edges(
        "supervisor", route_to_specialist, {"order_agent": "order_agent", "policy_agent": "policy_agent"}
    )
    graph.add_conditional_edges(
        "policy_agent",
        route_after_policy_agent,
        {"escalate": "escalate", "order_agent": "order_agent", "finalize": "finalize"},
    )
    graph.add_conditional_edges("order_agent", route_after_order_agent, {"tools": "tools", "finalize": "finalize"})
    graph.add_conditional_edges("tools", route_after_tools, {"escalate": "escalate", "order_agent": "order_agent"})
    graph.add_edge("finalize", END)
    graph.add_edge("escalate", END)

    return graph.compile(checkpointer=checkpointer)


__all__ = ["build_support_graph"]

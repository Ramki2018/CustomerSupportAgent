"""LangGraph workflow for the support agent.

    START -> redact_pii -> safety_check --(unsafe)--> escalate -> END
                               |
                          (safe) v
                        resolve_memory -> plan_and_retrieve -> agent --(tool calls)--> tools
                                                                 |  ^                    |
                                                          (reply) v  +--(continue)------+
                                                              finalize -> END            |
                                                                         (loop guard) -> escalate -> END

Every node is traced by LangSmith when tracing is enabled (see `config.py`).
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import SupportNodes
from .routing import route_after_agent, route_after_safety, route_after_tools
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
    graph.add_node("plan_and_retrieve", nodes.plan_and_retrieve)
    graph.add_node("agent", nodes.call_llm)
    graph.add_node("tools", nodes.run_tools)
    graph.add_node("escalate", nodes.escalate)
    graph.add_node("finalize", nodes.finalize)

    graph.add_edge(START, "redact_pii")
    graph.add_edge("redact_pii", "safety_check")
    graph.add_conditional_edges(
        "safety_check", route_after_safety, {"escalate": "escalate", "resolve_memory": "resolve_memory"}
    )
    graph.add_edge("resolve_memory", "plan_and_retrieve")
    graph.add_edge("plan_and_retrieve", "agent")
    graph.add_conditional_edges("agent", route_after_agent, {"tools": "tools", "finalize": "finalize"})
    graph.add_conditional_edges("tools", route_after_tools, {"escalate": "escalate", "agent": "agent"})
    graph.add_edge("finalize", END)
    graph.add_edge("escalate", END)

    return graph.compile(checkpointer=checkpointer)


__all__ = ["build_support_graph"]

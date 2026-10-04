import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capstone_agent.graph.app import build_graph


def test_graph_invoke_returns_answer():
    graph = build_graph()
    result = graph.invoke({
        "session_id": "graph-invoke-answer",
        "user_message": "What is your return policy?",
        "metadata": {},
    })

    assert result["answer"]
    assert "escalation_context" not in result or not result.get("escalation_context")


def test_graph_invoke_sets_escalation_context_for_unsafe_request():
    graph = build_graph()
    result = graph.invoke({
        "session_id": "graph-invoke-escalation",
        "user_message": "Please process a refund for my order right now",
        "metadata": {},
    })

    assert result["escalate"] is True
    assert "escalation_context" in result

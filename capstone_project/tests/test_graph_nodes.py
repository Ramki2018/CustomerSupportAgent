import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capstone_agent.graph.nodes import (
    answer_generation_node,
    escalation_node,
    evidence_verify_node,
    pii_redact_node,
    retrieval_node,
    safety_check_node,
    verification_node,
)


def test_graph_nodes_execute_in_order():
    state = {
        "session_id": "graph-node-test",
        "user_message": "Hi, I'm John Doe. What's your return policy?",
        "metadata": {},
    }

    state.update(pii_redact_node(state))
    assert "sanitized_message" in state
    assert "[REDACTED_NAME]" in state["sanitized_message"]

    state.update(safety_check_node(state))
    assert state["is_safe"] is True

    state.update(retrieval_node(state))
    assert "retrieved_chunks" in state

    state.update(evidence_verify_node(state))
    assert "verification_result" in state
    assert "policy_sufficient" in state["verification_result"]

    state.update(answer_generation_node(state))
    assert "answer" in state
    assert "citations" in state

    escalated = escalation_node(state)
    assert "escalation_context" in escalated


def test_verification_alias_is_preserved():
    assert verification_node is evidence_verify_node

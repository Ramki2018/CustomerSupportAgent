import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capstone_agent.graph.routing import route_after_safety, route_after_verification


def test_route_after_safety():
    assert route_after_safety({"is_safe": False}) == "refuse"
    assert route_after_safety({"is_safe": True}) == "retrieve"


def test_route_after_verification():
    assert route_after_verification({"verification_result": {"needs_escalation": True}}) == "escalate"
    assert route_after_verification({"verification_result": {"needs_escalation": False}}) == "generate"

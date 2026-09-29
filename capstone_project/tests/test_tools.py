"""Unit tests for tool safeguards and the return-eligibility bug fix (Phase 9 evidence).

Run with: pytest tests/
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from capstone_agent.safety import check as safety_check
from capstone_agent.tools import ToolError, ToolRegistry, tool_check_return_eligibility


def test_return_eligibility_bug_fix():
    # BUG: measuring from order_date understated eligibility for ORD-1002
    # (order_date 40 days ago, delivered_date 15 days ago).
    buggy = tool_check_return_eligibility("ORD-1002", _use_delivered_date=False)
    fixed = tool_check_return_eligibility("ORD-1002", _use_delivered_date=True)
    assert buggy["eligible"] is False
    assert fixed["eligible"] is True


def test_unknown_order_raises_tool_error():
    with pytest.raises(ToolError):
        tool_check_return_eligibility("ORD-0000")


def test_tool_registry_loop_prevention():
    registry = ToolRegistry(max_calls_per_turn=1)
    registry.execute("get_order_status", {"order_id": "ORD-1001"}, call_count=0)
    with pytest.raises(ToolError):
        registry.execute("get_order_status", {"order_id": "ORD-1001"}, call_count=1)


def test_tool_registry_rejects_unknown_tool():
    registry = ToolRegistry()
    with pytest.raises(ToolError):
        registry.execute("delete_all_orders", {}, call_count=0)


def test_safety_blocks_action_requests():
    decision = safety_check("Please process a refund for my order right now")
    assert decision.allowed is False
    assert decision.escalate is True


def test_safety_allows_informational_questions():
    decision = safety_check("What is your return policy?")
    assert decision.allowed is True

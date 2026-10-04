import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capstone_agent import config
from capstone_agent.agents.full_agent import FullAgent
from capstone_agent.graph.nodes import LOOP_GUARD_REPLY
from capstone_agent.llm_client import MockLLM
from capstone_agent.graph.routing import route_after_agent, route_after_safety, route_after_tools


@pytest.fixture
def agent(tmp_path, monkeypatch):
    # Keep long-term memory writes out of the real state/ directory.
    monkeypatch.setattr("capstone_agent.memory._LONG_TERM_PATH", tmp_path / "long_term_memory.json")
    agent = FullAgent()
    agent.llm = MockLLM()  # tests must be deterministic and never call the network
    return agent


class ExplodingLLM:
    def chat(self, messages, tools=None):
        raise AssertionError("LLM must not be called for this request")


class AlwaysToolCallLLM:
    def chat(self, messages, tools=None):
        call = {"id": "call-1", "type": "function",
                "function": {"name": "get_order_status", "arguments": '{"order_id": "ORD-1002"}'}}
        return {"role": "assistant", "content": None, "tool_calls": [call]}


def test_routing_functions_are_pure_and_deterministic():
    assert route_after_safety({"is_safe": False}) == "escalate"
    assert route_after_safety({"is_safe": True}) == "resolve_memory"
    assert route_after_agent({"pending_tool_calls": [{"x": 1}]}) == "tools"
    assert route_after_agent({"pending_tool_calls": []}) == "finalize"
    assert route_after_tools({"needs_ticket": True}) == "escalate"
    assert route_after_tools({"needs_ticket": False}) == "agent"


def test_refusal_never_reaches_llm_and_creates_ticket(agent):
    agent.llm = ExplodingLLM()
    result = agent.run_turn("graph-refusal", "Please process a refund for me right now.")

    assert result["path"] == ["redact_pii", "safety_check", "escalate"]
    assert result["escalated"] is True
    assert result["ticket_id"].startswith("ESC-")
    assert "can't modify orders" in result["reply"]


def test_faq_turn_is_grounded_in_retrieval(agent):
    result = agent.run_turn("graph-faq", "What is your return policy?")

    assert result["path"] == ["redact_pii", "safety_check", "resolve_memory", "plan_and_retrieve", "agent", "finalize"]
    assert result["grounding"] == "retrieval"
    assert "return_policy" in result["sources"]
    assert result["escalated"] is False


def test_tool_turn_uses_tool_result(agent):
    result = agent.run_turn("graph-tool", "Is order ORD-1002 eligible for a return?")

    assert "tools" in result["path"]
    assert result["grounding"] == "tool_result"
    assert result["sources"] == []
    assert "eligible" in result["reply"].lower()


def test_reply_always_mentions_the_ticket_it_created(agent):
    class ForgetfulLLM:
        """Simulates a real model that ignores the escalation ticket in the tool result."""

        def __init__(self):
            self.calls = 0

        def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                call = {"id": "call-9", "type": "function",
                        "function": {"name": "get_order_status", "arguments": '{"order_id": "ORD-9999"}'}}
                return {"role": "assistant", "content": None, "tool_calls": [call]}
            return {"role": "assistant", "content": "I can't find that order.", "tool_calls": None}

    agent.llm = ForgetfulLLM()
    result = agent.run_turn("graph-ticket", "What is the status of order ORD-9999?")

    assert result["escalated"] is True
    assert result["ticket_id"] in result["reply"]


def test_tool_result_messages_carry_the_tool_call_id(agent):
    """Regression: OpenAI rejects tool messages without the id of the call they answer."""

    class RecordingLLM:
        def __init__(self):
            self.calls = []

        def chat(self, messages, tools=None):
            self.calls.append([dict(m) for m in messages])
            if len(self.calls) == 1:
                call = {"id": "call-42", "type": "function",
                        "function": {"name": "get_order_status", "arguments": '{"order_id": "ORD-1002"}'}}
                return {"role": "assistant", "content": None, "tool_calls": [call]}
            return {"role": "assistant", "content": "done", "tool_calls": None}

    llm = RecordingLLM()
    agent.llm = llm
    agent.run_turn("graph-toolid", "What is the status of order ORD-1002?")

    second_call = llm.calls[1]
    assistant_call = next(m for m in second_call if m.get("tool_calls"))
    tool_message = next(m for m in second_call if m["role"] == "tool")
    assert assistant_call["tool_calls"][0]["type"] == "function"
    assert tool_message["tool_call_id"] == assistant_call["tool_calls"][0]["id"] == "call-42"


def test_openai_client_returns_tool_calls_in_api_shape(monkeypatch):
    """Regression: echoing a tool call back to OpenAI requires `type: function`."""
    from types import SimpleNamespace

    from capstone_agent.llm_client import OpenAILLM

    function = SimpleNamespace(name="get_order_status", arguments='{"order_id": "ORD-1002"}')
    message = SimpleNamespace(content=None, tool_calls=[SimpleNamespace(id="call-1", function=function)])
    completions = SimpleNamespace(create=lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=message)]))

    llm = OpenAILLM.__new__(OpenAILLM)
    llm._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    result = llm.chat([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])

    assert result["tool_calls"] == [{"id": "call-1", "type": "function", "function": {
        "name": "get_order_status", "arguments": '{"order_id": "ORD-1002"}'}}]


def test_unknown_order_escalates_via_tool_failure(agent):
    result = agent.run_turn("graph-unknown", "What is the status of order ORD-9999?")

    assert result["escalated"] is True
    assert result["ticket_id"].startswith("ESC-")


def test_checkpointer_memory_resolves_that_order(agent):
    session = "graph-memory"
    agent.run_turn(session, "What is the status of order ORD-1002?")
    result = agent.run_turn(session, "Can you check the status of that order and tell me if I can return it?")

    assert "ORD-1002" in result["reply"]
    assert "eligible" in result["reply"].lower()
    values = agent.graph.get_state(agent.thread_config(session)).values
    assert values["last_order_id"] == "ORD-1002"
    assert len(values["history"]) <= config.SHORT_TERM_MEMORY_TURNS


def test_per_turn_state_is_reset_between_turns(agent):
    session = "graph-reset"
    refused = agent.run_turn(session, "Please process a refund for me right now.")
    follow_up = agent.run_turn(session, "What is your return policy?")

    assert refused["escalated"] is True
    assert follow_up["escalated"] is False
    assert follow_up["ticket_id"] is None
    assert "escalate" not in follow_up["path"]


def test_tool_loop_guard_escalates(agent):
    agent.llm = AlwaysToolCallLLM()
    result = agent.run_turn("graph-loop", "What is the status of order ORD-1002?")

    assert result["reply"] == LOOP_GUARD_REPLY
    assert result["escalated"] is True
    assert result["path"].count("tools") == config.MAX_TOOL_CALLS_PER_TURN
    assert result["path"][-1] == "escalate"


def test_history_window_is_bounded(agent):
    session = "graph-window"
    for _ in range(config.SHORT_TERM_MEMORY_TURNS + 2):
        agent.run_turn(session, "What is your return policy?")

    values = agent.graph.get_state(agent.thread_config(session)).values
    assert len(values["history"]) == config.SHORT_TERM_MEMORY_TURNS


def test_graph_without_checkpointer_runs_a_single_turn(tmp_path, monkeypatch):
    monkeypatch.setattr("capstone_agent.memory._LONG_TERM_PATH", tmp_path / "long_term_memory.json")
    platform_agent = FullAgent(use_checkpointer=False)
    platform_agent.llm = MockLLM()
    platform_graph = platform_agent.graph
    result = platform_graph.invoke({"session_id": "graph-platform", "user_message": "What is your return policy?"})

    assert result["answer"]
    assert result["trace"][-1] == "finalize"


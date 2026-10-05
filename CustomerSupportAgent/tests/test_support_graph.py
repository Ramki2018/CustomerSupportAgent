import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from support_agent import config
from support_agent.agents.full_agent import FullAgent
from support_agent.graph.nodes import LOOP_GUARD_REPLY
from support_agent.llm_client import MockLLM
from support_agent.graph.routing import (
    route_after_order_agent,
    route_after_policy_agent,
    route_after_safety,
    route_after_tools,
    route_to_specialist,
)
from support_agent.tools import ORDER_AGENT_TOOLS, ToolError, ToolRegistry


@pytest.fixture
def agent(tmp_path, monkeypatch):
    # Keep long-term memory writes out of the real state/ directory.
    monkeypatch.setattr("support_agent.memory._LONG_TERM_PATH", tmp_path / "long_term_memory.json")
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
    assert route_to_specialist({"route": "order"}) == "order_agent"
    assert route_to_specialist({"route": "policy"}) == "policy_agent"
    assert route_to_specialist({"route": "both"}) == "policy_agent"
    assert route_after_policy_agent({"needs_ticket": True, "route": "both"}) == "escalate"
    assert route_after_policy_agent({"route": "both"}) == "order_agent"
    assert route_after_policy_agent({"route": "policy"}) == "finalize"
    assert route_after_order_agent({"pending_tool_calls": [{"x": 1}]}) == "tools"
    assert route_after_order_agent({"pending_tool_calls": []}) == "finalize"
    assert route_after_tools({"needs_ticket": True}) == "escalate"
    assert route_after_tools({"needs_ticket": False}) == "order_agent"


def test_refusal_never_reaches_llm_and_creates_ticket(agent):
    agent.llm = ExplodingLLM()
    result = agent.run_turn("graph-refusal", "Please process a refund for me right now.")

    assert result["path"] == ["redact_pii", "safety_check", "escalate"]
    assert result["escalated"] is True
    assert result["ticket_id"].startswith("ESC-")
    assert "can't modify orders" in result["reply"]


def test_faq_turn_goes_to_policy_agent_and_is_grounded(agent):
    result = agent.run_turn("graph-faq", "What is your return policy?")

    assert result["route"] == "policy"
    assert result["path"] == ["redact_pii", "safety_check", "resolve_memory", "supervisor", "policy_agent", "finalize"]
    assert result["grounding"] == "retrieval"
    assert "return_policy" in result["sources"]
    assert result["escalated"] is False


def test_tool_turn_goes_to_order_agent_and_uses_tool_result(agent):
    result = agent.run_turn("graph-tool", "Is order ORD-1002 eligible for a return?")

    assert result["route"] == "order"
    assert result["path"] == [
        "redact_pii", "safety_check", "resolve_memory", "supervisor",
        "order_agent", "tools", "order_agent", "finalize",
    ]
    assert result["grounding"] == "tool_result"
    assert result["sources"] == []
    assert "eligible" in result["reply"].lower()


def test_policy_agent_has_no_tools(agent):
    seen = {}

    class RecordingLLM:
        def chat(self, messages, tools=None):
            seen["tools"] = tools
            return {"role": "assistant", "content": "ok", "tool_calls": None}

    agent.llm = RecordingLLM()
    agent.run_turn("graph-policy-tools", "What is your return policy?")

    assert seen["tools"] is None


def test_order_agent_sees_no_policy_documents(agent):
    seen = {}

    def exploding_search(query, top_k=None):
        raise AssertionError("order agent must not retrieve policy documents")

    class RecordingLLM:
        def chat(self, messages, tools=None):
            seen["system"] = messages[0]["content"]
            seen["tools"] = [t["function"]["name"] for t in tools]
            return {"role": "assistant", "content": "ok", "tool_calls": None}

    agent.kb.search = exploding_search
    agent.llm = RecordingLLM()
    agent.run_turn("graph-order-docs", "What is the status of order ORD-1002?")

    assert "RETRIEVED CONTEXT" not in seen["system"]
    assert set(seen["tools"]) == set(ORDER_AGENT_TOOLS)


def test_supervisor_routes_resolved_pronoun_to_order_agent(agent):
    session = "graph-route-pronoun"
    agent.run_turn(session, "What is the status of order ORD-1002?")
    follow_up = agent.run_turn(session, "Can I return it?")
    unrelated = agent.run_turn(session, "How long does shipping usually take?")

    assert follow_up["route"] == "order"
    assert unrelated["route"] == "policy"


def test_mixed_request_runs_both_agents_and_merges_their_answers(agent):
    result = agent.run_turn("graph-both", "What is your return policy for order ORD-1002?")

    assert result["route"] == "both"
    assert result["path"] == [
        "redact_pii", "safety_check", "resolve_memory", "supervisor",
        "policy_agent", "order_agent", "tools", "order_agent", "finalize",
    ]
    assert result["grounding"] == "tool_result+retrieval"
    assert "eligible" in result["reply"].lower()          # order agent's part
    assert "policy documentation" in result["reply"]      # policy agent's part
    assert "return_policy" in result["sources"]


def test_model_written_sources_line_is_replaced_not_duplicated(agent):
    class ChattySourcesLLM:
        def chat(self, messages, tools=None):
            return {"role": "assistant", "content": "Standard shipping takes 3-5 days.\n\nSources: shipping_policy",
                    "tool_calls": None}

    agent.llm = ChattySourcesLLM()
    reply = agent.run_turn("graph-sources", "How long does shipping usually take?")["reply"]

    assert reply.count("Sources:") == 1
    assert reply.startswith("Standard shipping takes 3-5 days.")


def test_tool_registry_enforces_agent_permissions():
    registry = ToolRegistry()
    assert registry.execute("get_order_status", {"order_id": "ORD-1002"}, 0, allowed=ORDER_AGENT_TOOLS)["order_id"] == "ORD-1002"
    with pytest.raises(ToolError, match="not permitted"):
        registry.execute("get_order_status", {"order_id": "ORD-1002"}, 0, allowed=frozenset())


def test_escalation_is_idempotent_within_a_turn(agent):
    """A real model may call escalate_to_human after a tool failure already created a ticket."""

    class EscalatingLLM:
        def __init__(self):
            self.calls = 0

        def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                args = '{"order_id": "ORD-9999"}'
                name = "get_order_status"
            elif self.calls == 2:
                args = '{"reason": "customer asked", "session_id": "graph-idem"}'
                name = "escalate_to_human"
            else:
                return {"role": "assistant", "content": "Handed off.", "tool_calls": None}
            call = {"id": f"call-{self.calls}", "type": "function", "function": {"name": name, "arguments": args}}
            return {"role": "assistant", "content": None, "tool_calls": [call]}

    agent.llm = EscalatingLLM()
    result = agent.run_turn("graph-idem", "What is the status of order ORD-9999?")

    tickets = {m.group(0) for m in __import__("re").finditer(r"ESC-\d{5}", result["reply"])}
    assert result["escalated"] is True
    assert tickets == {result["ticket_id"]}


def test_policy_agent_tool_call_is_a_violation_that_escalates(agent):
    class RogueLLM:
        def chat(self, messages, tools=None):
            call = {"id": "call-1", "type": "function",
                    "function": {"name": "get_order_status", "arguments": '{"order_id": "ORD-1002"}'}}
            return {"role": "assistant", "content": None, "tool_calls": [call]}

    agent.llm = RogueLLM()
    result = agent.run_turn("graph-rogue", "What is your return policy?")

    assert result["path"][-2:] == ["policy_agent", "escalate"]
    assert result["escalated"] is True
    assert result["ticket_id"].startswith("ESC-")


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

    from support_agent.llm_client import OpenAILLM

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
    monkeypatch.setattr("support_agent.memory._LONG_TERM_PATH", tmp_path / "long_term_memory.json")
    platform_agent = FullAgent(use_checkpointer=False)
    platform_agent.llm = MockLLM()
    platform_graph = platform_agent.graph
    result = platform_graph.invoke({"session_id": "graph-platform", "user_message": "What is your return policy?"})

    assert result["answer"]
    assert result["trace"][-1] == "finalize"


import sys
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capstone_agent import config
from capstone_agent.agents.full_agent import FullAgent
from capstone_agent.logging_utils import sanitize_user_message
from capstone_agent.memory import ConversationMemory
from capstone_agent.feedback import FeedbackStore


def _read_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def test_memory_redacts_pii(tmp_path):
    # Use a unique session id to avoid collisions
    session_id = "test-session-pii"
    mem = ConversationMemory(session_id)
    # Remember a fact that contains an email (PII)
    mem.remember("note", "Contact: alice@example.com")
    content = _read_file(config.STATE_DIR / "long_term_memory.json")
    assert "alice@example.com" not in content


def test_feedback_redacts_pii(tmp_path):
    store = FeedbackStore()
    store.add("test-session-feedback", 5, "My email is bob@example.com")
    content = _read_file(config.STATE_DIR / "feedback.json")
    assert "bob@example.com" not in content


def test_user_message_is_sanitized_before_model_use(monkeypatch):
    agent = FullAgent()
    captured = {}

    class StubLLM:
        def chat(self, messages, tools=None):
            captured["messages"] = messages
            captured["tools"] = tools
            return {"role": "assistant", "content": "ok", "tool_calls": None}

    def fake_search(query, top_k=None):
        captured["query"] = query
        return []

    agent.llm = StubLLM()
    agent.kb.search = fake_search

    raw_message = (
        "Hi, I'm John Doe. Email me at john@example.com. "
        "My card 4111 1111 1111 1111 and account number ACC-1234567 are on file. "
        "I live at 123 Main Street."
    )
    reply = agent.handle_message("test-session-sanitize", raw_message)

    assert reply == "ok"

    expected = sanitize_user_message(raw_message)
    assert captured["query"] == expected
    user_message = captured["messages"][-1]["content"]
    assert user_message == expected
    assert "john@example.com" not in user_message
    assert "123 Main Street" not in user_message
    assert "4111 1111 1111 1111" not in user_message
    assert "ACC-1234567" not in user_message
    assert "John Doe" not in user_message
    assert "[REDACTED_EMAIL]" in user_message
    assert "[REDACTED_ADDRESS]" in user_message
    assert "[REDACTED_NAME]" in user_message
    assert "[REDACTED_CARD_NUMBER]" in user_message
    assert "[REDACTED_ACCOUNT_ID]" in user_message

    values = agent.graph.get_state(agent.thread_config("test-session-sanitize")).values
    assert values["history"][0]["content"] == expected

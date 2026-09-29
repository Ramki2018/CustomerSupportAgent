import sys
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capstone_agent import config
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

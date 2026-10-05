import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from support_agent import config
from support_agent import memory as capstone_memory
from support_agent.agents.full_agent import FullAgent
from support_agent.llm_client import MockLLM

# Distinctive values, so a match in any file means a real leak.
PII = {
    "email": "leakcheck.7731@example.com",
    "phone": "415 555 0177",
    "card": "4111 1111 1111 1111",
    "address": "4821 Quillfeather Avenue",
    "name": "Zelda Fitzgerald",
    "account": "ACCT-77310099",
}
PII_SUFFIX = (
    f" My name is {PII['name']}, email {PII['email']}, phone {PII['phone']}, card {PII['card']}, "
    f"I live at {PII['address']}, account number {PII['account']}."
)

# One message per route, so every code path that writes logs, tickets or state is covered.
MESSAGES = [
    "What is your return policy?" + PII_SUFFIX,                       # policy agent
    "What is the status of order ORD-1002?" + PII_SUFFIX,             # order agent + tools
    "What is the status of order ORD-9999?" + PII_SUFFIX,             # tool failure -> ticket
    "Please process a refund for me right now." + PII_SUFFIX,         # safety refusal -> ticket
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


@pytest.fixture
def run(tmp_path):
    agent = FullAgent()
    agent.llm = MockLLM()
    session = f"pii-logs-{uuid.uuid4().hex[:8]}"
    replies = [agent.run_turn(session, message) for message in MESSAGES]
    agent.record_feedback(session, 3, "Contact me at " + PII["email"])
    return agent, session, replies


def test_logs_were_actually_written_for_this_run(run):
    """Guards against a vacuous pass: the scan below only means something if the logs exist."""
    _, session, _ = run

    assert session in _read(config.LOGS_DIR / "interactions.jsonl")
    assert "support_graph" in _read(config.LOGS_DIR / "agent.log") or "tools" in _read(config.LOGS_DIR / "agent.log")


@pytest.mark.parametrize("kind", sorted(PII))
def test_no_pii_in_log_files(run, kind):
    value = PII[kind]
    for log in ("interactions.jsonl", "agent.log"):
        assert value not in _read(config.LOGS_DIR / log), f"{kind} leaked into {log}"


@pytest.mark.parametrize("kind", sorted(PII))
def test_no_pii_in_replies_or_tickets(run, kind):
    _, _, replies = run
    for turn in replies:
        assert PII[kind] not in turn["reply"]
        assert PII[kind] not in str(turn["ticket_id"])


@pytest.mark.parametrize("kind", sorted(PII))
def test_no_pii_in_memory_feedback_or_checkpoint(run, kind):
    agent, session, _ = run
    value = PII[kind]

    assert value not in _read(capstone_memory._LONG_TERM_PATH)
    assert value not in _read(agent.feedback_store.path)
    checkpoint = agent.graph.get_state(agent.thread_config(session)).values
    assert value not in str(checkpoint)


def test_order_ids_stay_readable_in_logs(run):
    """Order IDs are not personal data; redaction must not break audit trails."""
    _, session, _ = run

    assert "ORD-1002" in _read(config.LOGS_DIR / "interactions.jsonl")

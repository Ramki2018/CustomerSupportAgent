"""API-key protection on /chat and /feedback (deployment/app.py)."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from deployment import app as api  # noqa: E402

BODY = {"session_id": "s1", "message": "What is your return policy?"}
FEEDBACK = {"session_id": "s1", "rating": 5}


class _FakeAgent:
    def run_turn(self, session_id, message):
        return {
            "reply": "ok", "escalated": False, "ticket_id": "", "sources": [], "grounding": "none",
            "retrieval_score": None, "route": "policy", "path": ["finalize"],
        }

    def record_feedback(self, *args):
        pass


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "agent", _FakeAgent())
    monkeypatch.setattr(api, "_auth_warned", False)
    monkeypatch.delenv("APP_ENV", raising=False)
    return TestClient(api.app)


def test_valid_key_is_accepted(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "secret-key")
    assert client.post("/chat", json=BODY, headers={"X-API-Key": "secret-key"}).status_code == 200
    assert client.post("/feedback", json=FEEDBACK, headers={"X-API-Key": "secret-key"}).status_code == 200


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}, {"X-API-Key": ""}])
def test_missing_or_wrong_key_is_rejected(client, monkeypatch, headers):
    monkeypatch.setenv("API_KEY", "secret-key")
    assert client.post("/chat", json=BODY, headers=headers).status_code == 401
    assert client.post("/feedback", json=FEEDBACK, headers=headers).status_code == 401


def test_health_stays_open(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "secret-key")
    assert client.get("/health").status_code == 200


def test_auth_is_off_in_development_without_a_key(client, monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    assert client.post("/chat", json=BODY).status_code == 200


def test_production_without_a_key_refuses_requests(client, monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    assert client.post("/chat", json=BODY).status_code == 503
    assert client.post("/chat", json=BODY, headers={"X-API-Key": "anything"}).status_code == 503


def test_key_check_happens_before_validation_and_agent(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "secret-key")
    assert client.post("/chat", json={"session_id": "", "message": ""}).status_code == 401

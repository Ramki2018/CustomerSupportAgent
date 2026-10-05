"""Test isolation: keep every test's writes out of the real state/ directory.

Without this, tests and demos append to state/feedback.json and state/long_term_memory.json,
and the accumulated feedback silently changes which prompt variant later runs use.
"""
import pytest


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr("capstone_agent.feedback._FEEDBACK_PATH", tmp_path / "feedback.json")
    monkeypatch.setattr("capstone_agent.memory._LONG_TERM_PATH", tmp_path / "long_term_memory.json")

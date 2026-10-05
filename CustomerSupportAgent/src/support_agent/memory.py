"""Conversation memory: short-term (per-session) and long-term (cross-session) state.

Retention rule: short-term memory is capped at N turns (sliding window). Long-term
memory persists across sessions but only stores small non-PII facts/preferences
(e.g. "last_order_id"), never free-form personal data.
"""
import json
from collections import deque
from pathlib import Path

from . import config
from .logging_utils import redact_pii

_LONG_TERM_PATH = config.STATE_DIR / "long_term_memory.json"


class ConversationMemory:
    def __init__(self, session_id: str, max_turns: int = config.SHORT_TERM_MEMORY_TURNS):
        self.session_id = session_id
        self.max_turns = max_turns
        self.short_term: deque = deque(maxlen=max_turns)
        self.long_term: dict = self._load_long_term()

    def _load_long_term(self) -> dict:
        if _LONG_TERM_PATH.exists():
            all_data = json.loads(_LONG_TERM_PATH.read_text(encoding="utf-8"))
            return all_data.get(self.session_id, {})
        return {}

    def add_turn(self, role: str, content: str) -> None:
        self.short_term.append({"role": role, "content": content})

    def get_recent_context(self) -> list:
        return list(self.short_term)

    def remember(self, key: str, value) -> None:
        """Persist a small non-PII fact/preference to long-term memory."""
        self.long_term[key] = value
        self._save_long_term()

    def recall(self, key: str, default=None):
        return self.long_term.get(key, default)

    def _save_long_term(self) -> None:
        all_data = {}
        if _LONG_TERM_PATH.exists():
            all_data = json.loads(_LONG_TERM_PATH.read_text(encoding="utf-8"))
        # Redact PII before persisting long-term memory to disk (keep in-memory full data)
        safe_entry = {k: redact_pii(str(v)) for k, v in self.long_term.items()}
        all_data[self.session_id] = safe_entry
        _LONG_TERM_PATH.write_text(json.dumps(all_data, indent=2), encoding="utf-8")

    def reset_short_term(self) -> None:
        self.short_term.clear()

    def reset_long_term(self) -> None:
        self.long_term = {}
        self._save_long_term()

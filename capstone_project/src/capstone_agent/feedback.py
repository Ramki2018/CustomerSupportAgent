"""Feedback store + adaptive behaviour rules (Phase 7).

Kept as simple, explainable rules (not another LLM call) so behaviour changes
can be audited: "why did the agent get more concise?" -> because >=2 of the
last 10 feedback comments said responses were too long.
"""
import json
from datetime import datetime, timezone

from . import config
from .logging_utils import redact_pii

_FEEDBACK_PATH = config.STATE_DIR / "feedback.json"


class FeedbackStore:
    def __init__(self):
        self.records = self._load()

    def _load(self) -> list:
        if _FEEDBACK_PATH.exists():
            return json.loads(_FEEDBACK_PATH.read_text(encoding="utf-8"))
        return []

    def _save(self) -> None:
        # Write a PII-redacted copy to disk while keeping in-memory records intact
        safe_records = []
        for r in self.records:
            safe_r = dict(r)
            safe_r["comment"] = redact_pii(safe_r.get("comment", ""))
            safe_r["session_id"] = redact_pii(safe_r.get("session_id", ""))
            safe_records.append(safe_r)
        _FEEDBACK_PATH.write_text(json.dumps(safe_records, indent=2), encoding="utf-8")

    def add(self, session_id: str, rating: int, comment: str = "") -> None:
        """rating: 1 (bad) to 5 (good)."""
        self.records.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "rating": rating,
            "comment": comment,
        })
        self._save()

    def preference_hints(self) -> dict:
        """Derive simple, explainable behaviour adjustments from recent feedback."""
        hints = {"prefer_concise": False, "prefer_more_detail": False}
        recent = self.records[-10:]
        if not recent:
            return hints
        concise_votes = sum(
            1 for r in recent if "too long" in r["comment"].lower() or "too much" in r["comment"].lower()
        )
        detail_votes = sum(
            1 for r in recent if "too short" in r["comment"].lower() or "more detail" in r["comment"].lower()
        )
        avg_rating = sum(r["rating"] for r in recent) / len(recent)
        hints["prefer_concise"] = concise_votes >= 2
        hints["prefer_more_detail"] = detail_votes >= 2
        hints["avg_rating"] = round(avg_rating, 2)
        return hints

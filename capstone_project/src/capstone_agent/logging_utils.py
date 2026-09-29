"""Logging utilities with PII redaction (Safety Requirement: no personal data in logs)."""
import json
import logging
import re
from datetime import datetime, timezone

from . import config

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"\b(?:\+?\d[\s-]?){9,15}\b")
_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_ORDER_ID_KEEP_RE = re.compile(r"\bORD-\d{3,}\b")  # order IDs are not PII, keep them readable
_TICKET_ID_KEEP_RE = re.compile(r"\bESC-\d{3,}\b")


def redact_pii(text: str) -> str:
    """Strip emails/phone numbers/card-like numbers before anything is written to disk."""
    if not text:
        return text
    placeholders: dict = {}

    def _keep(match):
        token = f"__KEEP{len(placeholders)}__"
        placeholders[token] = match.group(0)
        return token

    text = _ORDER_ID_KEEP_RE.sub(_keep, text)
    text = _TICKET_ID_KEEP_RE.sub(_keep, text)
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = _CARD_RE.sub("[REDACTED_NUMBER]", text)
    text = _PHONE_RE.sub("[REDACTED_NUMBER]", text)
    for token, original in placeholders.items():
        text = text.replace(token, original)
    return text


class PIISafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.msg = redact_pii(str(record.msg))
        return super().format(record)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(config.LOGS_DIR / "agent.log", encoding="utf-8")
    handler.setFormatter(PIISafeFormatter("%(asctime)s | %(name)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
    stream = logging.StreamHandler()
    stream.setFormatter(PIISafeFormatter("%(message)s"))
    logger.addHandler(stream)
    logger.propagate = False
    return logger


def log_interaction(session_id: str, role: str, content: str, extra: dict | None = None) -> None:
    """Append a PII-redacted interaction record for evidence/audit purposes."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "role": role,
        "content": redact_pii(content or ""),
    }
    if extra:
        record["extra"] = {k: redact_pii(str(v)) for k, v in extra.items()}
    with open(config.LOGS_DIR / "interactions.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

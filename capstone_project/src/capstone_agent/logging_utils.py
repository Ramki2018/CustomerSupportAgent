"""Logging utilities with PII redaction.

The same redaction helper is also reused before user text is passed to memory,
retrieval, or an LLM so personal data does not leave the pre-processing layer.
"""
import copy
import json
import logging
import re
from datetime import datetime, timezone

from . import config

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"\b(?:\+?\d[\s-]?){9,15}\b")
_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
# "my name is <anything>" is a strong signal, so any case is redacted. "I am / I'm / this is" is
# ambiguous ("I'm being harassed"), so only a Capitalized name follows. Matching it
# case-insensitively used to erase safety-relevant words before the safety gate saw them.
_NAME_RE = re.compile(r"\b(my name is)\s+([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+){0,2})\b", re.IGNORECASE)
_NAME_WEAK_RE = re.compile(r"\b((?i:i am|i'm|this is))\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b")
_ADDRESS_RE = re.compile(
    r"\b\d{1,5}\s+(?:[A-Za-z0-9]+\s+){0,4}"
    r"(?:street|st\.?|road|rd\.?|avenue|ave\.?|lane|ln\.?|drive|dr\.?|"
    r"boulevard|blvd\.?|way|court|ct\.?|terrace|ter\.?|place|pl\.?|suite|ste\.?|apartment|apt\.?)\b",
    re.IGNORECASE,
)
_ACCOUNT_RE = re.compile(
    r"\b(?:account|acct|member|customer)\s*(?:id|number|no\.?|#)?\s*[:#-]?\s*[A-Z0-9][A-Z0-9-]{5,}\b",
    re.IGNORECASE,
)
_ORDER_ID_KEEP_RE = re.compile(r"\bORD-\d{3,}\b")  # order IDs are not PII, keep them readable
_TICKET_ID_KEEP_RE = re.compile(r"\bESC-\d{3,}\b")


def redact_pii(text: str) -> str:
    """Strip common PII before anything is written to disk or sent to a model."""
    if not text:
        return text
    placeholders: dict = {}

    def _keep(match):
        token = f"__KEEP{len(placeholders)}__"
        placeholders[token] = match.group(0)
        return token

    text = _ORDER_ID_KEEP_RE.sub(_keep, text)
    text = _TICKET_ID_KEEP_RE.sub(_keep, text)
    text = _NAME_RE.sub(lambda m: f"{m.group(1)} [REDACTED_NAME]", text)
    text = _NAME_WEAK_RE.sub(lambda m: f"{m.group(1)} [REDACTED_NAME]", text)
    text = _ADDRESS_RE.sub("[REDACTED_ADDRESS]", text)
    text = _ACCOUNT_RE.sub("[REDACTED_ACCOUNT_ID]", text)
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = _CARD_RE.sub("[REDACTED_CARD_NUMBER]", text)
    text = _PHONE_RE.sub("[REDACTED_PHONE_NUMBER]", text)
    for token, original in placeholders.items():
        text = text.replace(token, original)
    return text


def sanitize_user_message(text: str) -> str:
    """Return a model-safe version of user text by applying the redaction rules."""
    return redact_pii(text)


class PIISafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        safe_record = copy.copy(record)
        safe_record.msg = redact_pii(str(record.getMessage()))
        safe_record.args = ()
        return super().format(safe_record)


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

"""Deterministic safety layer implementing Scenario 3 safety requirements:
  - Must refuse unsafe or policy-violating requests.
  - Must not fabricate policies (handled in retrieval.py / prompts).
  - Must escalate sensitive or unresolved cases.
  - Must not store personal data in logs (handled in logging_utils.py).

Kept as plain Python regex rules rather than LLM judgment so refusal/escalation
behaviour is auditable and unit-testable (see tests/test_tools.py).
"""
import re

ACTION_KEYWORDS = [
    r"\bcancel my order\b", r"\bprocess (the |a )?refund\b", r"\bissue (the |a )?refund\b",
    r"\bcharge my card\b", r"\bupdate my (address|payment|card)\b", r"\bdelete my account\b",
    r"\bplace (an|the) order\b", r"\brefund for my\b.*\bright now\b",
]
LEGAL_ADVICE_KEYWORDS = [r"\bsue\b", r"\blawsuit\b", r"\blegal action\b", r"\bis this illegal\b"]
SENSITIVE_ESCALATION_KEYWORDS = [
    r"\bfraud\b", r"\bunauthorized charge\b", r"\bidentity theft\b", r"\bthreat(en)?\b",
    r"\bself[- ]harm\b", r"\bdiscriminat", r"\bharass",
]


def _matches_any(text: str, patterns: list) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


class SafetyDecision:
    def __init__(self, allowed: bool, reason: str = "", escalate: bool = False):
        self.allowed = allowed
        self.reason = reason
        self.escalate = escalate


def check(user_message: str) -> SafetyDecision:
    if _matches_any(user_message, ACTION_KEYWORDS):
        return SafetyDecision(
            allowed=False,
            reason=("This agent provides information and guidance only. It can't modify orders, "
                    "process refunds, or move money. I'm escalating this to a human agent who can."),
            escalate=True,
        )
    if _matches_any(user_message, LEGAL_ADVICE_KEYWORDS):
        return SafetyDecision(
            allowed=False,
            reason="I can't provide legal advice. I'm escalating this to a specialist team.",
            escalate=True,
        )
    if _matches_any(user_message, SENSITIVE_ESCALATION_KEYWORDS):
        return SafetyDecision(
            allowed=False,
            reason="This looks like a sensitive issue that needs a human specialist. Escalating now.",
            escalate=True,
        )
    return SafetyDecision(allowed=True)

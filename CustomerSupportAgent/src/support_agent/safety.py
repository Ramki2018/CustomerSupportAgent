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
    r"\bcancel my order\b", r"\bprocess (the |a )?refund\b", r"\bissue (the |a )?(full |partial )?refund\b",
    r"\bcharge my card\b", r"\bupdate my (address|payment|card)\b", r"\bdelete my account\b",
    r"\bplace (an|the) order\b", r"\brefund for my\b.*\bright now\b",
    # Paraphrased money-moving or order-changing requests. Kept to imperative phrasings so that
    # policy questions ("Can I change the shipping address after placing an order?") still pass.
    r"\b(reverse|undo|revert)\b[^.?!]{0,30}\b(payment|charge|transaction|purchase|order)\b",
    r"\bmy money back\b", r"\bput the (money|funds) back\b",
    r"\bsend (me )?(the )?(money|funds)\b[^.?!]{0,15}\bback\b",
    r"\b(approve|authori[sz]e|grant)\b[^.?!]{0,20}\brefunds?\b",
    r"\bcancel\b(?:\s+\w+){0,2}\s+(?:order|ord-\d+)\b",
    r"\b(change|update|modify|edit|switch|redirect|reroute)\b[^.?!]{0,40}\b(address|parcel|package|delivery)\b[^.?!]{0,30}(?:\bto\b|:)",
    r"\b(take|deduct|withdraw|debit)\b[^.?!]{0,40}\b(out of|from)\s+my\s+(account|card|bank)\b",
]
# Attempts to override the agent's rules. Refused and escalated like other unsafe requests.
INJECTION_KEYWORDS = [
    r"\b(ignore|disregard|forget|override|bypass)\b[^.?!]{0,25}\b(previous|prior|above|earlier|your|the|all)\b[^.?!]{0,20}\b(instructions?|rules?|guidelines|policies|prompt)\b",
    r"\bforget everything\b", r"\bfrom now on you\b",
    r"\b(admin|developer|debug|god|unrestricted)\s+mode\b", r"\bjailbreak\b", r"\bsystem prompt\b",
    r"\byou are now\b[^.?!]{0,30}\b(mode|admin|free|unrestricted)\b", r"\bpretend (to be|you are)\b",
]
LEGAL_ADVICE_KEYWORDS = [
    r"\bsue\b", r"\blawsuit\b", r"\blegal action\b", r"\bis this illegal\b",
    r"\b(lawyer|attorney|solicitor)\b", r"\blegal (claim|proceedings|notice)\b", r"\bis (it|that|this) legal\b",
]
SENSITIVE_ESCALATION_KEYWORDS = [
    r"\bfraud\b", r"\bunauthori[sz]ed\b", r"\bidentity theft\b", r"\bthreat(en)?\b",
    r"\bself[- ]harm\b", r"\bdiscriminat", r"\bharass",
    r"\bwithout my (permission|consent|authori[sz]ation|knowledge)\b",
    r"\bcharge\b[^.?!]{0,50}\b(never|didn't|did not)\b[^.?!]{0,15}\b(make|made|authori[sz]e|authori[sz]ed|place|placed)\b",
    r"\bsomeone (used|charged|stole|accessed|hacked)\b", r"\b(stolen|hacked|compromised)\b",
]


def _matches_any(text: str, patterns: list) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


class SafetyDecision:
    def __init__(self, allowed: bool, reason: str = "", escalate: bool = False):
        self.allowed = allowed
        self.reason = reason
        self.escalate = escalate


# General "what does the policy say" questions mention actions (cancel, refund) without asking the agent to
# perform one. They are answered from the knowledge base. Anything tied to a specific order or the customer's
# own account ("my order", ORD-1001) is still treated as a request for action.
_QUESTION_START = re.compile(
    r"^\s*(is|are|can|could|do|does|will|would|what|how|when|why|where|which|am)\b", re.IGNORECASE
)
_POLICY_WORDS = re.compile(
    r"\b(policy|policies|rules?|terms|allowed|permitted|possible|eligible|eligibility)\b", re.IGNORECASE
)
_PERSONAL_REFERENCE = re.compile(r"\b(my|mine|i|me|ord-\d+)\b", re.IGNORECASE)
# How-to and capability questions ("How do I cancel an order?", "Can I cancel an order after it ships?",
# "Can the assistant issue a refund?") ask what is possible, not for the agent to act. "Can you ..." and
# "Could you ..." are excluded because those are polite requests. Any sign of a concrete request (the
# customer's own order, an order ID, "for me", urgency, "please") keeps the message refused.
_INFORMATIONAL_START = re.compile(
    r"^\s*(how\s+(do|can|should|would)\s+(i|we)\b|(can|could|may)\s+(i|we)\b"
    r"|can\s+(the|this)\s+(support\s+)?(assistant|agent|bot|chatbot)\b|is\s+it\s+possible\s+to\b"
    r"|where\s+(do|can)\s+(i|we)\b)",
    re.IGNORECASE,
)
_REQUEST_MARKERS = re.compile(
    r"\b(my|mine|for me|ord-\d+|right now|now|immediately|right away|asap|please|today|just do it)\b",
    re.IGNORECASE,
)


def is_policy_question(text: str) -> bool:
    general_policy = bool(
        _QUESTION_START.search(text) and _POLICY_WORDS.search(text) and not _PERSONAL_REFERENCE.search(text)
    )
    informational = bool(_INFORMATIONAL_START.search(text) and not _REQUEST_MARKERS.search(text))
    return general_policy or informational


def check(user_message: str) -> SafetyDecision:
    if _matches_any(user_message, ACTION_KEYWORDS) and not is_policy_question(user_message):
        return SafetyDecision(
            allowed=False,
            reason=("This agent provides information and guidance only. It can't modify orders, "
                    "process refunds, or move money. I'm escalating this to a human agent who can."),
            escalate=True,
        )
    if _matches_any(user_message, INJECTION_KEYWORDS):
        return SafetyDecision(
            allowed=False,
            reason=("I can't change how I follow my guidelines or act on that request. "
                    "I'm escalating this to a human agent."),
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

def check_layered(user_message: str) -> SafetyDecision:
    """Regex gate first, then the embedding classifier for phrasings the rules do not cover.

    The classifier fails open: if it is disabled or errors, the regex decision stands.
    """
    decision = check(user_message)
    if not decision.allowed or is_policy_question(user_message):
        return decision

    from . import config

    if not config.SAFETY_CLASSIFIER_ENABLED:
        return decision
    try:
        from .logging_utils import get_logger
        from .safety_classifier import get_classifier

        verdict = get_classifier().classify(user_message)
    except Exception:
        get_logger("safety").exception("Safety classifier failed; using the regex decision only")
        return decision
    if verdict.blocked:
        return SafetyDecision(allowed=False, reason=verdict.reason, escalate=True)
    return decision

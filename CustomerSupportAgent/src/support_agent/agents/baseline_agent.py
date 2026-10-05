"""Phase 2: Baseline agent — pure rule/template matching. No LLM, no memory,
no retrieval. Deliberately simple so its limitations are obvious and motivate
every later phase (see `run_baseline_demo`).
"""
import re

from ..logging_utils import get_logger, log_interaction

logger = get_logger("baseline_agent")

TEMPLATES = [
    (re.compile(r"\breturn\b", re.IGNORECASE),
     "You can return items within 30 days of delivery. Please provide your order ID."),
    (re.compile(r"\bshipping\b", re.IGNORECASE), "Standard shipping takes 3-5 business days."),
    (re.compile(r"\bwarranty\b", re.IGNORECASE), "Most products include a 1-year warranty."),
    (re.compile(r"\border status\b|\btrack\b", re.IGNORECASE), "Please share your order ID to check its status."),
]

DEFAULT_RESPONSE = "Sorry, I don't understand. Please rephrase your question."


class BaselineAgent:
    """Known limitations (demonstrated in `run_baseline_demo`):
    1. No paraphrase understanding — only exact keyword matches trigger a response.
    2. No memory — can't use context from earlier turns (e.g. an order ID given previously).
    """

    def respond(self, session_id: str, message: str) -> str:
        log_interaction(session_id, "user", message)
        for pattern, template in TEMPLATES:
            if pattern.search(message):
                log_interaction(session_id, "assistant", template)
                return template
        log_interaction(session_id, "assistant", DEFAULT_RESPONSE)
        return DEFAULT_RESPONSE


def run_baseline_demo():
    agent = BaselineAgent()
    session_id = "demo-baseline"
    questions = [
        "What's your return policy?",
        "Can I get my money back on something I bought two weeks ago?",  # paraphrase -> fails
        "My order ORD-1002, is it eligible?",  # needs context/reasoning -> fails
    ]
    for q in questions:
        print(f"USER: {q}\nAGENT: {agent.respond(session_id, q)}\n")


if __name__ == "__main__":
    run_baseline_demo()

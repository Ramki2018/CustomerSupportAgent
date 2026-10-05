"""Phase 3: LLM-integrated agent with multiple prompt strategies.

Required method (Prompt Comparison Rule): `compare_prompts` runs the same
question set across all prompt variants for a side-by-side comparison table.
"""
from ..llm_client import get_llm_client
from ..logging_utils import get_logger, log_interaction, sanitize_user_message
from ..safety import check as safety_check

logger = get_logger("llm_agent")

PROMPT_VARIANTS = {
    "v1_basic": "You are a helpful customer support assistant.",
    "v2_role_and_constraints": (
        "You are an AI Support Resolution Agent for an online retail company. "
        "Only answer using known policy information. If you are unsure, say so and offer "
        "escalation. Never invent policy details."
    ),
    "v3_role_constraints_concise": (
        "You are an AI Support Resolution Agent for an online retail company. "
        "Only answer using known policy information. If unsure, say so and offer escalation. "
        "Never invent policy details. Keep answers concise, under 3 sentences."
    ),
}
DEFAULT_VARIANT = "v2_role_and_constraints"


class LLMAgent:
    def __init__(self, variant: str = DEFAULT_VARIANT):
        self.llm = get_llm_client()
        self.variant = variant

    def respond(self, session_id: str, message: str, variant: str | None = None) -> str:
        safe_message = sanitize_user_message(message)
        log_interaction(session_id, "user", safe_message)
        decision = safety_check(safe_message)
        if not decision.allowed:
            log_interaction(session_id, "assistant", decision.reason, {"safety_block": True})
            return decision.reason

        system_prompt = PROMPT_VARIANTS[variant or self.variant]
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": safe_message}]
        result = self.llm.chat(messages)
        content = result["content"] or ""
        log_interaction(session_id, "assistant", content, {"prompt_variant": variant or self.variant})
        return content

    def compare_prompts(self, questions: list) -> list:
        """Run the same test set across every prompt variant (required for Phase 3/
        the Prompt Comparison Rule): Prompt -> Output, for later What Improved/Worsened notes."""
        rows = []
        for q in questions:
            row = {"question": q}
            for variant in PROMPT_VARIANTS:
                row[variant] = self.respond("demo-prompt-compare", q, variant=variant)
            rows.append(row)
        return rows

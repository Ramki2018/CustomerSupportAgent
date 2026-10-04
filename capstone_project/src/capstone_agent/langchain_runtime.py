"""LangChain-based model helpers for generation and structured verification.

These helpers keep the project deployable in two modes:
- offline/demo mode: deterministic fallbacks
- live model mode: ChatOpenAI + structured outputs
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field

from . import config
from .llm_client import MockLLM
from .logging_utils import get_logger

logger = get_logger("langchain_runtime")


class EvidenceVerification(BaseModel):
    policy_sufficient: bool = Field(..., description="Whether retrieved policy evidence is enough.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence from 0.0 to 1.0.")
    needs_escalation: bool = Field(..., description="Whether the case should be escalated.")
    reasoning: str = Field(..., description="Short explanation of the decision.")


@lru_cache(maxsize=1)
def _chat_model():
    if config.USE_MOCK_LLM or not config.OPENAI_API_KEY:
        return None
    try:
        from langchain_openai import ChatOpenAI
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.exception("Failed to import langchain_openai: %s", exc)
        return None
    return ChatOpenAI(
        model=config.MODEL_NAME,
        temperature=0.0,
        api_key=config.OPENAI_API_KEY,
    )


def get_chat_model():
    """Return the cached ChatOpenAI instance, or None in offline mode."""
    return _chat_model()


def warm_up_langchain_runtime() -> None:
    """Instantiate cached LangChain resources ahead of the first request."""
    _chat_model()


def _retrieved_context_text(retrieved_chunks: list[dict]) -> str:
    lines: list[str] = []
    for chunk in retrieved_chunks[:5]:
        lines.append(
            f"- SOURCE: {chunk.get('doc_id', 'unknown')}\n"
            f"  SCORE: {chunk.get('score', 0)}\n"
            f"  TEXT: {chunk.get('text', '')}"
        )
    return "\n".join(lines)


def _fallback_verification(retrieved_chunks: list[dict]) -> EvidenceVerification:
    has_evidence = bool(retrieved_chunks)
    return EvidenceVerification(
        policy_sufficient=has_evidence,
        confidence=0.9 if has_evidence else 0.0,
        needs_escalation=not has_evidence,
        reasoning=(
            "Retrieval returned policy evidence."
            if has_evidence
            else "No supporting policy evidence was retrieved."
        ),
    )


def verify_evidence(user_message: str, retrieved_chunks: list[dict]) -> EvidenceVerification:
    """Return a structured evidence-verification decision.

    Uses a LangChain structured-output model when available; otherwise falls
    back to a deterministic heuristic so offline demo mode still works.
    """
    model = _chat_model()
    if model is None:
        return _fallback_verification(retrieved_chunks)

    prompt = (
        "You are a support-policy verifier. Judge whether the retrieved policy "
        "evidence is sufficient to answer the customer. Return a strict JSON "
        "object with fields: policy_sufficient, confidence, needs_escalation, reasoning.\n\n"
        f"USER MESSAGE:\n{user_message}\n\n"
        f"RETRIEVED POLICY CHUNKS:\n{_retrieved_context_text(retrieved_chunks)}"
    )
    try:
        structured = model.with_structured_output(EvidenceVerification)
        result = structured.invoke(prompt)
        if isinstance(result, EvidenceVerification):
            return result
        return EvidenceVerification.model_validate(result)
    except Exception as exc:
        logger.warning("Structured evidence verification failed; using fallback: %s", exc)
        return _fallback_verification(retrieved_chunks)


def generate_answer(
    user_message: str,
    retrieved_chunks: list[dict],
    verification_result: dict,
    *,
    follow_up_suggestions: list[str] | None = None,
) -> str:
    """Generate a grounded support answer with LangChain when available."""
    model = _chat_model()
    context = _retrieved_context_text(retrieved_chunks)
    follow_up_text = ""
    if follow_up_suggestions:
        follow_up_text = "\n".join(f"- {item}" for item in follow_up_suggestions)

    if model is None:
        fallback = MockLLM()
        messages = [
            {"role": "system", "content": "You are a grounded customer support assistant."},
            {
                "role": "user",
                "content": (
                    f"User message: {user_message}\n\n"
                    f"Retrieved context:\n{context}\n\n"
                    f"Verification:\n{json.dumps(verification_result)}\n\n"
                    f"Follow-up suggestions:\n{follow_up_text}"
                ),
            },
        ]
        return fallback.chat(messages)["content"] or ""

    prompt = (
        "You are a grounded customer support assistant.\n"
        "Answer only from the supplied policy context. If the context is not enough, "
        "say so and recommend escalation. Keep the answer concise and cite the most relevant source names.\n\n"
        f"USER MESSAGE:\n{user_message}\n\n"
        f"POLICY CONTEXT:\n{context}\n\n"
        f"VERIFICATION RESULT:\n{json.dumps(verification_result)}\n\n"
        f"FOLLOW-UP SUGGESTIONS:\n{follow_up_text}"
    )
    try:
        response = model.invoke(prompt)
        return getattr(response, "content", "") or ""
    except Exception as exc:
        logger.warning("LangChain answer generation failed; using fallback: %s", exc)
        fallback = MockLLM()
        messages = [
            {"role": "system", "content": "You are a grounded customer support assistant."},
            {"role": "user", "content": prompt},
        ]
        return fallback.chat(messages)["content"] or ""

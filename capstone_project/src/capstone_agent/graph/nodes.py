"""Node functions for the LangGraph workflow.

These nodes reuse the current project logic so the graph can be introduced
without rewriting the existing safety and retrieval behavior. Each node returns
only the fields it owns, which keeps the state updates explicit and easy to
debug.
"""

from __future__ import annotations

from ..langchain_runtime import generate_answer, verify_evidence
from ..logging_utils import sanitize_user_message
from ..retrieval import KnowledgeBase
from ..safety import check as safety_check
from .state import AgentState

_KB = KnowledgeBase()


def pii_redact_node(state: AgentState) -> AgentState:
    user_message = state.get("user_message", "")
    sanitized = sanitize_user_message(user_message)
    return {
        "user_message": user_message,
        "sanitized_message": sanitized,
        "metadata": {
            **(state.get("metadata") or {}),
            "pii_redacted": True,
        },
    }


def safety_check_node(state: AgentState) -> AgentState:
    sanitized_message = state.get("sanitized_message", state.get("user_message", ""))
    decision = safety_check(sanitized_message)
    return {
        "is_safe": decision.allowed,
        "safety_reason": decision.reason,
        "escalate": decision.escalate,
        "metadata": {
            **(state.get("metadata") or {}),
            "safety_checked": True,
            "unsafe_message": not decision.allowed,
        },
    }


def retrieval_node(state: AgentState) -> AgentState:
    sanitized_message = state.get("sanitized_message", "")
    results = _KB.search(sanitized_message)
    retrieved_chunks = [
        {
            "doc_id": chunk.doc_id,
            "text": chunk.text,
            "score": score,
            "metadata": {
                "source": chunk.doc_id,
                "retrieval_backend": "tfidf",
            },
        }
        for score, chunk in results
    ]
    return {
        "retrieved_chunks": retrieved_chunks,
        "metadata": {
            **(state.get("metadata") or {}),
            "retrieval_backend": "tfidf",
            "retrieval_count": len(retrieved_chunks),
        },
    }


def evidence_verify_node(state: AgentState) -> AgentState:
    retrieved_chunks = state.get("retrieved_chunks", [])
    verification = verify_evidence(state.get("sanitized_message", state.get("user_message", "")), retrieved_chunks)
    return {
        "verification_result": {
            "policy_sufficient": verification.policy_sufficient,
            "confidence": verification.confidence,
            "needs_escalation": verification.needs_escalation,
            "reasoning": verification.reasoning,
        }
    }


def answer_generation_node(state: AgentState) -> AgentState:
    retrieved_chunks = state.get("retrieved_chunks", [])
    if not retrieved_chunks:
        return {
            "answer": "I couldn't find a matching policy document, so I don't want to guess. I can escalate this to a human agent.",
            "citations": [],
            "follow_up_suggestions": ["Contact support", "Upload the relevant policy document"],
            "metadata": {
                **(state.get("metadata") or {}),
                "answer_mode": "no_evidence",
            },
        }

    top = retrieved_chunks[0]
    citations = [
        {
            "source": chunk.get("doc_id"),
            "excerpt": chunk.get("text", "")[:240],
            "score": chunk.get("score"),
        }
        for chunk in retrieved_chunks[:3]
    ]
    suggestions = ["Check return policy", "Ask about warranty coverage"]
    if any("shipping" in (chunk.get("doc_id") or "").lower() for chunk in retrieved_chunks):
        suggestions.insert(0, "Review shipping policy")
    answer = generate_answer(
        state.get("sanitized_message", state.get("user_message", "")),
        retrieved_chunks,
        state.get("verification_result", {}),
        follow_up_suggestions=suggestions[:3],
    )
    return {
        "answer": answer,
        "citations": citations,
        "follow_up_suggestions": suggestions[:3],
        "metadata": {
            **(state.get("metadata") or {}),
            "answer_mode": "grounded",
        },
    }


def escalation_node(state: AgentState) -> AgentState:
    return {
        "escalate": True,
        "answer": "This case should be handled by a human support agent.",
        "escalation_context": {
            "session_id": state.get("session_id"),
            "sanitized_message": state.get("sanitized_message", ""),
            "safety_reason": state.get("safety_reason", ""),
            "retrieved_chunks": state.get("retrieved_chunks", []),
            "verification_result": state.get("verification_result", {}),
        },
        "metadata": {
            **(state.get("metadata") or {}),
            "escalated": True,
        },
    }


# Backward-compatible alias for the earlier scaffold name.
verification_node = evidence_verify_node

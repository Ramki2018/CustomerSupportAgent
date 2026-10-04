"""Shared state for the support-agent LangGraph workflow.

Fields fall into three groups:
  - input:      `session_id`, `user_message` (callers should pass PII-sanitized text;
                the `redact_pii` node re-applies redaction as defense in depth)
  - persisted:  `history` and `last_order_id` live in the checkpointer, keyed by
                `thread_id == session_id`, so they carry across turns
  - per-turn:   everything else is reset by the `redact_pii` node at the start of a turn
"""

from typing import Annotated, TypedDict

from .. import config


def window(existing: list | None, new: list | None) -> list:
    """Reducer: append new turns, keeping only the last N (sliding-window short-term memory)."""
    return ((existing or []) + (new or []))[-config.SHORT_TERM_MEMORY_TURNS:]


class SupportState(TypedDict, total=False):
    # input
    session_id: str
    user_message: str

    # persisted across turns (checkpointer)
    history: Annotated[list[dict], window]
    last_order_id: str

    # per-turn
    sanitized_message: str
    is_safe: bool
    safety_reason: str
    plan: list[str]
    prompt_variant: str
    retrieved: list[dict]
    sources: list[str]
    messages: list[dict]
    pending_tool_calls: list[dict]
    tool_calls_made: int
    needs_ticket: bool
    escalation_reason: str
    escalated: bool
    ticket_id: str
    user_turn_recorded: bool
    answer: str
    grounding: str
    trace: list[str]

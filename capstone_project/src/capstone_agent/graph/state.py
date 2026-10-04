"""Shared state object passed between LangGraph nodes.

This is the message-passing contract for the graph. Each node should read the
fields it needs and write only the fields it owns so the workflow stays
deterministic and easy to inspect.
"""

from typing import TypedDict


class AgentState(TypedDict, total=False):
    session_id: str
    user_message: str
    sanitized_message: str
    is_safe: bool
    safety_reason: str
    retrieved_chunks: list[dict]
    verification_result: dict
    answer: str
    escalate: bool
    citations: list[dict]
    metadata: dict
    follow_up_suggestions: list[str]
    escalation_context: dict

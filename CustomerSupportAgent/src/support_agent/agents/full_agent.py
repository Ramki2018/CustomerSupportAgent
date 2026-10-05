"""Phase 6 & 7: planning, memory, and adaptive behaviour on top of ToolAgent.

This is the production agent used for deployment (Phase 8) and evaluation (Phase 9).
Its workflow is a LangGraph `StateGraph` (see `graph/app.py`); this class is a thin
facade that wires the agent's components into the graph and runs one turn at a time.
"""
from langgraph.checkpoint.memory import MemorySaver

from ..feedback import FeedbackStore
from ..graph.app import build_support_graph
from ..logging_utils import sanitize_user_message
from ..memory import ConversationMemory
from .tool_agent import DEFAULT_VARIANT, ToolAgent


class FullAgent(ToolAgent):
    def __init__(self, variant: str = DEFAULT_VARIANT, use_checkpointer: bool = True):
        super().__init__(variant)
        self.feedback_store = FeedbackStore()
        # Long-term (cross-session, non-PII) facts only; short-term history lives in the
        # graph checkpoint, keyed by thread_id == session_id.
        self._memories: dict = {}
        self.graph = build_support_graph(self, checkpointer=MemorySaver() if use_checkpointer else None)

    def _memory(self, session_id: str) -> ConversationMemory:
        if session_id not in self._memories:
            self._memories[session_id] = ConversationMemory(session_id)
        return self._memories[session_id]

    @staticmethod
    def thread_config(session_id: str) -> dict:
        return {
            "configurable": {"thread_id": session_id},
            "recursion_limit": 25,
            "run_name": "support_turn",
            "tags": ["support-agent"],
            "metadata": {"session_id": session_id},
        }

    def run_turn(self, session_id: str, message: str) -> dict:
        """Run one conversation turn through the graph and return a structured result."""
        # Sanitize at the boundary so raw PII never enters graph state or checkpoints.
        state = self.graph.invoke(
            {"session_id": session_id, "user_message": sanitize_user_message(message)},
            self.thread_config(session_id),
        )
        return {
            "reply": state.get("answer", ""),
            "escalated": bool(state.get("escalated")),
            "ticket_id": state.get("ticket_id") or None,
            "sources": state.get("sources", []),
            "grounding": state.get("grounding", ""),
            "retrieval_score": state.get("retrieval_score"),
            "route": state.get("route") or None,
            "path": state.get("trace", []),
        }

    def handle_message(self, session_id: str, message: str) -> str:
        return self.run_turn(session_id, message)["reply"]

    def record_feedback(self, session_id: str, rating: int, comment: str = "") -> None:
        self.feedback_store.add(session_id, rating, comment)

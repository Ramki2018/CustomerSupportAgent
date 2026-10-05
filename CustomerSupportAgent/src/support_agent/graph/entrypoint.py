"""LangGraph deployment entrypoint (LangGraph Platform / LangSmith Deployments).

Exposes the same graph that the API, demo, and evaluation run. No checkpointer is
attached here because the hosting platform supplies its own persistence.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The platform loads this file by path, so make the package importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from support_agent.agents.full_agent import FullAgent  # noqa: E402

graph = FullAgent(use_checkpointer=False).graph

__all__ = ["graph"]

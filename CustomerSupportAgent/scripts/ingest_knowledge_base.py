"""CLI entrypoint for ingesting the knowledge base into Qdrant."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from support_agent import config
from support_agent.rag.ingestion import ingest_knowledge_base


def main() -> int:
    result = ingest_knowledge_base(config.KNOWLEDGE_BASE_DIR)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

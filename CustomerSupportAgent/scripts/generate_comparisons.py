"""Generates the Phase 3/4 comparison evidence used in docs/02_prompt_comparison.md:
  - Same test set across 3 prompt variants (Prompt Comparison Rule).
  - With vs without retrieval, to show RAG's improvement over the baseline LLM.
Run: python scripts/generate_comparisons.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from support_agent import config
from support_agent.agents.llm_agent import LLMAgent
from support_agent.agents.rag_agent import RagAgent

PROMPT_TEST_QUESTIONS = [
    "What is your return policy?",
    "How long does shipping take?",
    "Do you price match competitors?",
]

RAG_TEST_QUESTIONS = [
    "What is your return policy?",
    "Is there a warranty on electronics?",
    "Do you price match competitors?",
]


def main():
    # Real-model runs are written to separate *_openai.json files so the offline evidence is kept.
    suffix = "_openai" if (not config.USE_MOCK_LLM and config.OPENAI_API_KEY) else ""
    llm_agent = LLMAgent()
    prompt_rows = llm_agent.compare_prompts(PROMPT_TEST_QUESTIONS)
    (config.STATE_DIR / f"prompt_comparison{suffix}.json").write_text(json.dumps(prompt_rows, indent=2), encoding="utf-8")

    rag_agent = RagAgent()
    rag_rows = rag_agent.compare_with_without_retrieval(RAG_TEST_QUESTIONS)
    (config.STATE_DIR / f"rag_comparison{suffix}.json").write_text(json.dumps(rag_rows, indent=2), encoding="utf-8")

    print(json.dumps({"prompt_rows": prompt_rows, "rag_rows": rag_rows}, indent=2))


if __name__ == "__main__":
    main()


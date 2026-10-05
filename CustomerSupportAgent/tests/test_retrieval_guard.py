import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from support_agent import config
from support_agent.agents.full_agent import FullAgent
from support_agent.graph.nodes import NO_DOCS_REPLY, assess_retrieval
from support_agent.llm_client import MockLLM
from support_agent.retrieval import Chunk


def _chunk(doc_id: str, raw: float, backend: str = "semantic") -> dict:
    return {"doc_id": doc_id, "text": f"{doc_id} text", "score": raw, "raw_score": raw, "backend": backend}


@pytest.fixture
def agent():
    agent = FullAgent()
    agent.llm = MockLLM()
    return agent


def _stub_search(agent, scored_docs, backend="semantic"):
    """Make the knowledge base return fixed (doc, raw score) results, best first."""
    results = [(raw + 2.0, Chunk(doc, f"{doc} text", raw, backend)) for doc, raw in scored_docs]
    agent.kb.search = lambda query, top_k=None: results


def test_nothing_retrieved_is_not_confident():
    assert assess_retrieval([]) == ([], None, False)


def test_best_score_below_the_floor_is_not_confident():
    relevant, best, confident = assess_retrieval([_chunk("shipping_policy", 0.25), _chunk("faq", 0.2)])

    assert confident is False
    assert relevant == []
    assert best == 0.25


def test_floor_is_per_backend():
    # 0.15 is noise for semantic similarity but a usable match for the weaker TF-IDF fallback.
    assert assess_retrieval([_chunk("faq", 0.15, "semantic")])[2] is False
    assert assess_retrieval([_chunk("faq", 0.15, "tfidf")])[2] is True


def test_marginal_chunks_are_dropped_relative_to_the_best():
    chunks = [_chunk("shipping_policy", 0.72), _chunk("return_policy", 0.43), _chunk("faq", 0.21)]
    relevant, best, confident = assess_retrieval(chunks)

    assert confident is True
    assert best == 0.72
    assert [r["doc_id"] for r in relevant] == ["shipping_policy"]


def test_comparable_chunks_are_all_kept():
    chunks = [_chunk("faq", 0.37), _chunk("return_policy", 0.36), _chunk("shipping_policy", 0.34)]

    assert len(assess_retrieval(chunks)[0]) == 3


def test_unscored_chunks_are_trusted():
    chunks = [{"doc_id": "faq", "text": "x", "score": 1.0, "raw_score": 0.0, "backend": ""}]

    assert assess_retrieval(chunks) == (chunks, None, True)


def test_low_confidence_skips_the_llm_and_says_so(agent):
    class ExplodingLLM:
        def chat(self, messages, tools=None):
            raise AssertionError("LLM must not be called when nothing relevant was retrieved")

    _stub_search(agent, [("shipping_policy", 0.05), ("faq", 0.03)])
    agent.llm = ExplodingLLM()
    result = agent.run_turn("guard-low", "What is the weather today?")

    assert result["reply"] == NO_DOCS_REPLY
    assert result["grounding"] == "none"
    assert result["sources"] == []
    assert result["escalated"] is False
    assert result["retrieval_score"] == 0.05
    assert result["path"][-2:] == ["policy_agent", "finalize"]


def test_confident_retrieval_still_answers_and_cites_only_relevant_sources(agent):
    seen = {}

    class RecordingLLM:
        def chat(self, messages, tools=None):
            seen["system"] = messages[0]["content"]
            return {"role": "assistant", "content": "Standard shipping takes 3-5 business days.", "tool_calls": None}

    _stub_search(agent, [("shipping_policy", 0.72), ("return_policy", 0.43), ("faq", 0.21)])
    agent.llm = RecordingLLM()
    result = agent.run_turn("guard-sources", "How long does shipping usually take?")

    assert result["sources"] == ["shipping_policy"]
    assert result["reply"].endswith("Sources: shipping_policy")
    # The model only sees the relevant document, so the answer and the Sources line agree.
    assert "shipping_policy text" in seen["system"]
    assert "return_policy text" not in seen["system"]
    assert result["retrieval_score"] == 0.72


def test_retrieval_score_is_reset_each_turn(agent):
    session = "guard-reset"
    _stub_search(agent, [("shipping_policy", 0.72)])
    first = agent.run_turn(session, "How long does shipping usually take?")
    second = agent.run_turn(session, "What is the status of order ORD-1002?")

    assert first["retrieval_score"] == 0.72
    assert second["route"] == "order"
    assert second["retrieval_score"] is None


def test_thresholds_are_configured_for_both_backends():
    assert set(config.MIN_RETRIEVAL_SCORE) == {"semantic", "tfidf"}
    assert 0 < config.SOURCE_RELATIVE_CUTOFF < 1

"""The TF-IDF fallback must cover the same sources as ingestion (markdown and PDF)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from support_agent import config, retrieval  # noqa: E402

PDF_SOURCE = "customer-support-policy-boundaries"


class _DownStore:
    def search(self, *args, **kwargs):
        raise RuntimeError("vector store unavailable")


@pytest.fixture
def offline_kb(monkeypatch):
    monkeypatch.setattr(retrieval, "get_default_vector_store", lambda: _DownStore())
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: object())
    return retrieval.KnowledgeBase


def test_fallback_includes_pdf_chunks(offline_kb):
    if not (config.KNOWLEDGE_BASE_DIR / f"{PDF_SOURCE}.pdf").exists():
        pytest.skip("knowledge-base PDF not present")
    kb = offline_kb()
    assert PDF_SOURCE in {chunk.doc_id for chunk in kb.chunks}
    assert {"return_policy", "shipping_policy", "faq"} <= {chunk.doc_id for chunk in kb.chunks}


def test_fallback_search_finds_pdf_content_when_qdrant_is_down(offline_kb):
    if not (config.KNOWLEDGE_BASE_DIR / f"{PDF_SOURCE}.pdf").exists():
        pytest.skip("knowledge-base PDF not present")
    results = offline_kb().search("Who completes order cancellation requests and subscription cancellation?")

    assert results and results[0][1].backend == "tfidf"
    assert PDF_SOURCE in {chunk.doc_id for _, chunk in results}


def test_markdown_only_directory_still_loads(offline_kb, tmp_path):
    (tmp_path / "return_policy.md").write_text("# Returns\n\nItems may be returned within 30 days.", encoding="utf-8")
    kb = offline_kb(tmp_path)
    assert {chunk.doc_id for chunk in kb.chunks} == {"return_policy"}


def test_falls_back_to_markdown_when_ingestion_loader_fails(offline_kb, tmp_path, monkeypatch):
    (tmp_path / "shipping_policy.md").write_text("# Shipping\n\nStandard shipping takes 3-5 business days.", encoding="utf-8")

    def broken(_directory):
        raise ImportError("PyMuPDF missing")

    monkeypatch.setattr(retrieval, "collect_chunks", broken)
    kb = offline_kb(tmp_path)
    assert {chunk.doc_id for chunk in kb.chunks} == {"shipping_policy"}

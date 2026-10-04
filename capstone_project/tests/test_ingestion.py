import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capstone_agent.rag.ingestion import collect_chunks, ingest_knowledge_base


class DummyEmbeddingProvider:
    def embed_documents(self, texts):
        return [[float(len(text))] * 4 for text in texts]


class DummyVectorStore:
    def __init__(self):
        self.documents = None

    def upsert_documents(self, documents):
        self.documents = documents


def test_collect_chunks_extracts_metadata(tmp_path):
    kb_dir = tmp_path / "knowledge_base"
    kb_dir.mkdir()
    (kb_dir / "return_policy.md").write_text(
        "# Return Policy\n\nCustomers may return items within 30 days.\n",
        encoding="utf-8",
    )

    chunks = collect_chunks(kb_dir)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.source == "return_policy.md"
    assert chunk.page is None
    assert chunk.section == "Return Policy"
    assert chunk.policy_type == "return"
    assert "Customers may return items within 30 days." in chunk.text


def test_ingest_knowledge_base_uses_vector_store(tmp_path):
    kb_dir = tmp_path / "knowledge_base"
    kb_dir.mkdir()
    (kb_dir / "shipping_policy.md").write_text(
        "# Shipping Policy\n\nStandard shipping takes 3-5 business days.\n",
        encoding="utf-8",
    )

    store = DummyVectorStore()
    result = ingest_knowledge_base(
        kb_dir,
        embedding_provider=DummyEmbeddingProvider(),
        vector_store=store,
        collection_name="test-collection",
    )

    assert result["documents"] == 1
    assert result["vector_size"] == 4
    assert result["collection_name"] == "test-collection"
    assert result["policy_types"] == ["shipping"]
    assert store.documents is not None
    assert store.documents[0]["payload"]["source"] == "shipping_policy.md"

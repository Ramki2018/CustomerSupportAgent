"""Knowledge-base ingestion pipeline for markdown and PDF policy documents."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .embeddings import EmbeddingProvider, get_embedding_provider
from .vector_store import QdrantVectorStore, VectorStore

_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_POLICY_TYPE_RULES = {
    "return": "return",
    "refund": "return",
    "shipping": "shipping",
    "warranty": "warranty",
    "faq": "faq",
    "privacy": "privacy",
    "account": "account",
    "payment": "payment",
    "cancellation": "cancellation",
    "cancel": "cancellation",
    "escalation": "escalation",
}


@dataclass(frozen=True)
class IngestedChunk:
    id: str
    text: str
    source: str
    page: int | None
    section: str | None
    policy_type: str

    def as_payload(self) -> dict:
        return {
            "text": self.text,
            "source": self.source,
            "page": self.page,
            "section": self.section,
            "policy_type": self.policy_type,
        }


def detect_policy_type(path: Path) -> str:
    lowered = path.stem.lower()
    for needle, policy_type in _POLICY_TYPE_RULES.items():
        if needle in lowered:
            return policy_type
    return "general"


def split_markdown_sections(text: str) -> list[tuple[str | None, str]]:
    sections: list[tuple[str | None, str]] = []
    current_heading: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        content = "\n".join(buffer).strip()
        if content:
            sections.append((current_heading, content))
        buffer = []

    for line in text.splitlines():
        heading_match = _MARKDOWN_HEADING_RE.match(line.strip())
        if heading_match:
            flush()
            current_heading = heading_match.group(2).strip()
            continue
        buffer.append(line)

    flush()
    return sections


def chunk_text(text: str, *, max_words: int = 160, overlap: int = 24) -> list[str]:
    words = text.split()
    if not words:
        return []
    if len(words) <= max_words:
        return [text.strip()]

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(len(words), start + max_words)
        chunk = " ".join(words[start:end]).strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(words):
            break
        start = max(0, end - overlap)
    return chunks


def _stable_chunk_id(source: str, page: int | None, index: int, text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    page_part = page if page is not None else 0
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source}:{page_part}:{index}:{digest}"))


def _extract_markdown_chunks(path: Path) -> list[IngestedChunk]:
    chunks: list[IngestedChunk] = []
    policy_type = detect_policy_type(path)
    for section_index, (section, section_text) in enumerate(split_markdown_sections(path.read_text(encoding="utf-8"))):
        for chunk_index, chunk_text_value in enumerate(chunk_text(section_text)):
            chunks.append(
                IngestedChunk(
                    id=_stable_chunk_id(path.stem, None, section_index * 100 + chunk_index, chunk_text_value),
                    text=chunk_text_value,
                    source=path.stem,
                    page=None,
                    section=section,
                    policy_type=policy_type,
                )
            )
    return chunks


def _extract_pdf_chunks(path: Path) -> list[IngestedChunk]:
    try:
        import fitz  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency path
        raise ImportError(
            "PyMuPDF (fitz) is not installed. Install pymupdf to ingest PDF files."
        ) from exc

    chunks: list[IngestedChunk] = []
    policy_type = detect_policy_type(path)
    doc = fitz.open(path.as_posix())
    try:
        for page_number, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if not text:
                continue
            section = None
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if lines:
                section = lines[0][:120]
            for chunk_index, chunk_text_value in enumerate(chunk_text(text)):
                chunks.append(
                    IngestedChunk(
                        id=_stable_chunk_id(path.stem, page_number, chunk_index, chunk_text_value),
                        text=chunk_text_value,
                        source=path.stem,
                        page=page_number,
                        section=section,
                        policy_type=policy_type,
                    )
                )
    finally:
        doc.close()
    return chunks


def collect_chunks(source_dir: Path) -> list[IngestedChunk]:
    """Read markdown and PDF files and convert them into searchable chunks."""
    chunks: list[IngestedChunk] = []
    for path in sorted(source_dir.iterdir()):
        if path.is_dir():
            continue
        suffix = path.suffix.lower()
        if suffix == ".md":
            chunks.extend(_extract_markdown_chunks(path))
        elif suffix == ".pdf":
            chunks.extend(_extract_pdf_chunks(path))
    return chunks


def ingest_knowledge_base(
    source_dir: Path,
    *,
    collection_name: str | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    vector_store: VectorStore | None = None,
) -> dict:
    """Build embeddings for the knowledge base and push the chunks to Qdrant."""
    chunks = collect_chunks(source_dir)
    if not chunks:
        raise ValueError(f"No .md or .pdf documents found in {source_dir}")

    provider = embedding_provider or get_embedding_provider()
    texts = [chunk.text for chunk in chunks]
    vectors = provider.embed_documents(texts)
    if not vectors:
        raise ValueError("Embedding provider returned no vectors.")

    vector_size = len(vectors[0])
    documents = []
    for chunk, vector in zip(chunks, vectors):
        documents.append(
            {
                "id": chunk.id,
                "vector": vector,
                "payload": chunk.as_payload(),
            }
        )

    store = vector_store
    if store is None:
        store = QdrantVectorStore(
            collection_name=collection_name
            or os.getenv("QDRANT_COLLECTION", "customer_support_policies"),
            vector_size=vector_size,
        )

    store.upsert_documents(documents)
    return {
        "source_dir": str(source_dir),
        "documents": len(chunks),
        "vector_size": vector_size,
        "collection_name": getattr(store, "collection_name", collection_name),
        "policy_types": sorted({chunk.policy_type for chunk in chunks}),
    }

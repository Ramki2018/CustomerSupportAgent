"""Lightweight retrieval-augmented generation (RAG) layer.

Uses Qdrant-backed semantic search when the vector store is available, and
falls back to a pure-Python TF-IDF index when semantic retrieval is not ready.
That keeps the project runnable in offline/demo environments while still
demonstrating the end-to-end semantic retrieval path required by the deployed
agent.
"""
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import config
from .rag.embeddings import get_embedding_provider
from .rag.vector_store import get_default_vector_store

_TOKEN_RE = re.compile(r"[a-zA-Z']+")
_STOPWORDS = {
    "the", "a", "an", "is", "are", "to", "of", "and", "or", "for", "in", "on", "it",
    "this", "that", "with", "as", "be", "can", "if", "you", "your", "i", "do", "does",
    "we", "our", "at", "by", "from", "will", "not", "have", "has", "not", "so",
}


def _policy_hint(query: str) -> str | None:
    lowered = query.lower()
    if any(term in lowered for term in ("shipping", "delivery", "deliver", "arrive", "arrival", "business day", "business days", "ship")):
        return "shipping"
    if any(term in lowered for term in ("return", "refund", "refunds", "eligible")):
        return "return"
    if "warranty" in lowered:
        return "warranty"
    if "faq" in lowered:
        return "faq"
    return None


def _boost_results(results: list[tuple[float, "Chunk"]], query: str) -> list[tuple[float, "Chunk"]]:
    hint = _policy_hint(query)
    if hint is None:
        return results

    boosted: list[tuple[float, Chunk]] = []
    for score, chunk in results:
        doc_id = chunk.doc_id.lower()
        adjusted = score
        if hint in doc_id:
            adjusted += 2.0
        elif hint == "shipping" and "delivery" in doc_id:
            adjusted += 1.0
        boosted.append((adjusted, chunk))
    boosted.sort(key=lambda item: item[0], reverse=True)
    return boosted


def _tokenize(text: str) -> list:
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS]


@dataclass
class Chunk:
    doc_id: str
    text: str
    # Raw similarity before the topical boost, and which backend produced it. The boosted
    # ranking score can't be used to judge relevance, and the two backends use different scales.
    raw_score: float = 0.0
    backend: str = ""


def _chunk_text(text: str, doc_id: str, max_words: int = 120) -> list:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip() and not p.strip().startswith("#")]
    chunks, buf, word_count = [], [], 0
    for para in paragraphs:
        words = para.split()
        if word_count + len(words) > max_words and buf:
            chunks.append(Chunk(doc_id, " ".join(buf)))
            buf, word_count = [], 0
        buf.extend(words)
        word_count += len(words)
    if buf:
        chunks.append(Chunk(doc_id, " ".join(buf)))
    return chunks


class KnowledgeBase:
    def __init__(self, directory: Path = config.KNOWLEDGE_BASE_DIR):
        self.chunks: list = []
        for path in sorted(directory.glob("*.md")):
            self.chunks.extend(_chunk_text(path.read_text(encoding="utf-8"), path.stem))

        self._doc_term_counts = [Counter(_tokenize(c.text)) for c in self.chunks]
        n_docs = len(self.chunks)
        doc_freq: Counter = Counter()
        for term_counts in self._doc_term_counts:
            for term in term_counts:
                doc_freq[term] += 1
        self._idf = {term: math.log((1 + n_docs) / (1 + df)) + 1 for term, df in doc_freq.items()}
        self._doc_vectors = [self._to_tfidf_vector(tc) for tc in self._doc_term_counts]
        self._doc_norms = [math.sqrt(sum(v * v for v in vec.values())) or 1.0 for vec in self._doc_vectors]
        self._semantic_store = get_default_vector_store()
        self._embedding_provider = get_embedding_provider()

    def _to_tfidf_vector(self, term_counts: Counter) -> dict:
        return {term: count * self._idf.get(term, 0.0) for term, count in term_counts.items()}

    def _cosine_similarity(self, query_vec: dict, query_norm: float, doc_index: int) -> float:
        doc_vec = self._doc_vectors[doc_index]
        dot = sum(weight * doc_vec.get(term, 0.0) for term, weight in query_vec.items())
        denom = query_norm * self._doc_norms[doc_index]
        return dot / denom if denom else 0.0

    def search(self, query: str, top_k: int = config.RETRIEVAL_TOP_K) -> list:
        """Returns a list of (score, Chunk) pairs, best first.

        Semantic Qdrant search is tried first; TF-IDF is a fallback for offline
        environments or when the vector store is unavailable.
        """
        try:
            semantic_results = self._semantic_store.search(
                query,
                top_k=top_k,
                embedding_provider=self._embedding_provider,
            )
        except Exception:
            semantic_results = []

        if semantic_results:
            semantic_pairs = [
                (result["score"], Chunk(result["doc_id"], result["text"], result["score"], "semantic"))
                for result in semantic_results
            ]
            return _boost_results(semantic_pairs, query)

        if not self.chunks:
            return []
        query_terms = Counter(_tokenize(query))
        query_vec = self._to_tfidf_vector(query_terms)
        query_norm = math.sqrt(sum(v * v for v in query_vec.values())) or 1.0
        scored = [(self._cosine_similarity(query_vec, query_norm, i), chunk) for i, chunk in enumerate(self.chunks)]
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [
            (score, Chunk(chunk.doc_id, chunk.text, score, "tfidf"))
            for score, chunk in scored[:top_k]
            if score > 0
        ]
        return _boost_results(top, query)

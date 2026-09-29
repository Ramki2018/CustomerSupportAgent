"""Lightweight retrieval-augmented generation (RAG) layer.

Implements TF-IDF vectors + cosine similarity in pure Python (no numpy/scipy/
sklearn) as a dependency-light, fully offline stand-in for neural embeddings +
a FAISS/Chroma vector store. Kept dependency-free deliberately: this workspace's
security policy blocks some compiled numpy/scipy binaries, and a pure-Python
implementation is also trivially portable/reproducible for grading. The
`KnowledgeBase.search` interface is the swap point if real embeddings/a real
vector store are wired in later (see docs/04_engineering_justification.md).
"""
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import config

_TOKEN_RE = re.compile(r"[a-zA-Z']+")
_STOPWORDS = {
    "the", "a", "an", "is", "are", "to", "of", "and", "or", "for", "in", "on", "it",
    "this", "that", "with", "as", "be", "can", "if", "you", "your", "i", "do", "does",
    "we", "our", "at", "by", "from", "will", "not", "have", "has", "not", "so",
}


def _tokenize(text: str) -> list:
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS]


@dataclass
class Chunk:
    doc_id: str
    text: str


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

    def _to_tfidf_vector(self, term_counts: Counter) -> dict:
        return {term: count * self._idf.get(term, 0.0) for term, count in term_counts.items()}

    def _cosine_similarity(self, query_vec: dict, query_norm: float, doc_index: int) -> float:
        doc_vec = self._doc_vectors[doc_index]
        dot = sum(weight * doc_vec.get(term, 0.0) for term, weight in query_vec.items())
        denom = query_norm * self._doc_norms[doc_index]
        return dot / denom if denom else 0.0

    def search(self, query: str, top_k: int = config.RETRIEVAL_TOP_K) -> list:
        """Returns a list of (score, Chunk) pairs, best first. Empty if nothing relevant
        is found — callers must handle this case rather than let the LLM guess."""
        if not self.chunks:
            return []
        query_terms = Counter(_tokenize(query))
        query_vec = self._to_tfidf_vector(query_terms)
        query_norm = math.sqrt(sum(v * v for v in query_vec.values())) or 1.0
        scored = [(self._cosine_similarity(query_vec, query_norm, i), chunk) for i, chunk in enumerate(self.chunks)]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [(score, chunk) for score, chunk in scored[:top_k] if score > 0]

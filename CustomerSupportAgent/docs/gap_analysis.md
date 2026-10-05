# Gap Analysis: Blueprint vs. Current Implementation

Reference: [architecture_blueprint.md](architecture_blueprint.md) compared with the current `CustomerSupportAgent/` project.
Status checked against the code and `requirements.txt`. The earlier version of this file described a TF-IDF-only
prototype and is replaced by this one. For design rationale see [04_engineering_justification.md](04_engineering_justification.md),
and for test evidence see [evidence.md](evidence.md).

## Summary

| # | Blueprint component | Status | What exists now |
|---|---|---|---|
| 1 | Qdrant vector database | ✅ Implemented | `rag/vector_store.py` (`QdrantVectorStore`): cosine collection `customer_support_policies`; connects to a Qdrant server (`QDRANT_URL`) and falls back to a local on-disk store under `.qdrant/`; failures are logged. `docker-compose.yml` runs Qdrant. |
| 2 | BGE-M3 dense + sparse embeddings | ⚠️ Different choice | `rag/embeddings.py`: dense `sentence-transformers/all-MiniLM-L6-v2` (configurable via `EMBEDDING_MODEL`), with a deterministic hashing encoder as offline fallback. No sparse or hybrid retrieval. |
| 3 | PDF knowledge-base ingestion (PyMuPDF) | ⚠️ Pipeline only | `rag/ingestion.py` ingests `.md` and `.pdf` (PyMuPDF, page metadata) and `scripts/ingest_knowledge_base.py` pushes to Qdrant. The knowledge base itself still has 4 markdown files and no PDFs. |
| 4 | LangGraph orchestration | ✅ Implemented | `graph/` (state, nodes, routing, app, entrypoint); `langgraph.json` for optional hosting. |
| 5 | PII redaction before model-facing steps | ✅ Implemented | `redact_pii` node runs first; redaction also applied to every log write and formatter output. |
| 6 | LLM-based safety classifier | ❌ Not implemented | Safety is deterministic regex rules in `safety.py` (action, prompt-injection, legal, sensitive). Measured on a fixed set, not guaranteed on unseen phrasing. |
| 7 | Evidence verification and confidence scoring | ⚠️ Partial | A retrieval-confidence gate on raw similarity (0.30 semantic, 0.10 TF-IDF) skips the LLM when nothing relevant is found. There is no post-generation verification of the answer against the sources. |
| 8 | Page-level citations | ⚠️ Partial | Qdrant payloads carry `source`, `chunk_id`, `page`, `section`, `policy_type`; the reply cites document names only. |
| 9 | Follow-up suggestions | ❌ Not implemented | |
| 10 | Rich metadata schema in vector payloads | ✅ Implemented | See item 8 for the payload fields. |
| 11 | Docker Compose for Qdrant | ✅ Implemented | `docker-compose.yml` (API + Qdrant); the API also runs without Docker using the local store. |
| 12 | Response caching | ❌ Not implemented | Only the vector store and embedding provider are cached in-process. |
| 13 | Distributed tracing / observability | ⚠️ Partial | Optional LangSmith tracing (off by default), per-request latency/error logging, and per-node PII-redacted log lines. No OpenTelemetry or metrics. |
| 14 | Models and components registry | ❌ Not implemented | Model and backend choices live in `config.py` and `.env`. |
| 15 | `prohibited_requests.md` in the knowledge base | ❌ Not implemented | Prohibited requests are handled in code by `safety.py`, not by retrieval. |

**Overall:** the four critical blueprint items are done or deliberately replaced (items 1 to 4), plus PII redaction,
Docker Compose and the metadata schema. The remaining gaps are quality and scale upgrades, not missing core
architecture.

## Details on the open items

### 2. Embeddings (BGE-M3 not used)
MiniLM was chosen for a small download and offline-friendly operation. Tradeoff: lower multilingual and hybrid
recall than BGE-M3. Retrieval relevance floors in `config.MIN_RETRIEVAL_SCORE` were measured with MiniLM and must be
re-measured if the model changes.

### 3. Knowledge base content
Ingestion supports PDFs, but only the four markdown documents (`return_policy`, `shipping_policy`,
`warranty_policy`, `faq`) are present. Policies such as cancellation, payment and privacy are absent, so such questions
get the fixed "no documentation" reply by design.

### 6. Safety classifier
A second-layer classifier behind the regex gate, plus an unseen adversarial test set, is the main safety next step.
A missed request cannot trigger an action, because no tool can refund, cancel or change an address, but it may not
produce an escalation ticket.

### 7 to 9. Answer quality
Post-generation grounding checks, page-level citations (the page and section data is already stored), and follow-up
suggestions would improve the reply quality and auditability.

### 12 to 14. Infrastructure
Caching, OpenTelemetry and a models registry matter once traffic or the number of models grows. State is also local
disk and single-replica, so a shared store (for example Postgres or Redis) comes before horizontal scaling.

## Dependencies

All blueprint packages that were adopted are in `requirements.txt`: `qdrant-client`, `pymupdf`,
`sentence-transformers` and `langgraph`. `FlagEmbedding` (BGE-M3) and `opentelemetry-sdk` are not used.

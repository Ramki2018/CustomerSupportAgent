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
| 3 | PDF knowledge-base ingestion (PyMuPDF) | ✅ Implemented (one combined PDF) | `rag/ingestion.py` ingests `.md` and `.pdf` (PyMuPDF, per-page chunks with page numbers) and `scripts/ingest_knowledge_base.py` pushes to Qdrant. The knowledge base now has `customer-support-policy-boundaries.pdf`, a 6-page "Demo Retail Policies" sample (cancellation, refunds, payments, privacy, escalation, as Q&A) plus 5 markdown files. The blueprint's separate policy PDFs are replaced by this one sample; its content is illustrative, not approved company policy. |
| 4 | LangGraph orchestration | ✅ Implemented | `graph/` (state, nodes, routing, app, entrypoint); `langgraph.json` for optional hosting. |
| 5 | PII redaction before model-facing steps | ✅ Implemented | `redact_pii` node runs first; redaction also applied to every log write and formatter output. |
| 6 | Second-layer safety classifier | ✅ Implemented (embedding-based, not an LLM) | Regex gate first, then `safety_classifier.py` (similarity to labelled unsafe and legitimate exemplars) for phrasings the rules miss. Coverage is measured on a small held-out set, not guaranteed; see details below. |
| 7 | Evidence verification and confidence scoring | ⚠️ Partial | A retrieval-confidence gate on raw similarity (0.30 semantic, 0.10 TF-IDF) skips the LLM when nothing relevant is found. There is no post-generation verification of the answer against the sources. |
| 8 | Page-level citations | ⚠️ Partial | Qdrant payloads carry `source`, `chunk_id`, `page`, `section`, `policy_type` and PDF chunks have real page numbers (1 to 6), but `retrieval.py` drops the page and the reply cites the document name only. The stored `section` for PDF chunks is the first line of the page, which is the same "DEMO POLICY" banner on every page, not the topic heading. |
| 9 | Follow-up suggestions | ❌ Not implemented | |
| 10 | Rich metadata schema in vector payloads | ✅ Implemented | See item 8 for the payload fields. |
| 11 | Docker Compose for Qdrant | ✅ Implemented | `docker-compose.yml` (API + Qdrant); the API also runs without Docker using the local store. |
| 12 | Response caching | ❌ Not implemented | Only the vector store and embedding provider are cached in-process. |
| 13 | Distributed tracing / observability | ⚠️ Partial | Optional LangSmith tracing (off by default), per-request latency/error logging, and per-node PII-redacted log lines. No OpenTelemetry or metrics. |
| 14 | Models and components registry | ❌ Not implemented | Model and backend choices live in `config.py` and `.env`. |
| 15 | `prohibited_requests.md` in the knowledge base | ✅ Implemented | `data/knowledge_base/prohibited_requests.md` describes what the assistant cannot do and which cases are escalated, so informational questions about this are answered from a cited source. Enforcement is still deterministic in `safety.py`, which runs before retrieval. |
| 16 | Offline fallback covers the whole knowledge base | ✅ Implemented | `KnowledgeBase` in `retrieval.py` now loads chunks through `collect_chunks` from `rag/ingestion.py`, so the TF-IDF fallback searches the PDF as well as the markdown files. If PDF support is unavailable it falls back to markdown only and logs why. Tests: `tests/test_knowledge_base_fallback.py`. |
| 17 | Safety gate vs. the PDF content | ✅ Fixed | `safety.is_policy_question` now also exempts how-to and capability questions ("How do I cancel an order?", "Can I cancel an order after it has shipped?", "Can the assistant issue a refund?") so they reach retrieval. Requests stay refused: "Can you ..." / "Could you ...", "my order", order IDs, "for me", "now" and "please". Tests: `tests/test_safety_rules.py`. |

**Overall:** the four critical blueprint items are done or deliberately replaced (items 1 to 4), plus PII redaction,
the second-layer safety classifier, Docker Compose, the metadata schema and the prohibited-requests document. The
remaining gaps are quality and scale upgrades (items 2, 7 to 9 and 12 to 14),
not missing core architecture.

## Details on the open items

### 2. Embeddings (BGE-M3 not used)
MiniLM was chosen for a small download and offline-friendly operation. Tradeoff: lower multilingual and hybrid
recall than BGE-M3. Retrieval relevance floors in `config.MIN_RETRIEVAL_SCORE` were measured with MiniLM and must be
re-measured if the model changes.

### 3. Knowledge base content
The knowledge base holds five markdown documents (`return_policy`, `shipping_policy`, `warranty_policy`, `faq`,
`prohibited_requests`) and `customer-support-policy-boundaries.pdf`, a 6-page "Demo Retail Policies" sample covering
cancellation, refunds, payments, privacy and escalation as customer-style Q&A. It states plainly that it is Amazon-inspired
illustrative content, not official or approved policy, so replace it with the organization's approved terms before
production. Two practical notes: the hyphenated file name is treated as an account ID by the PII log redactor (log output
only), and the earlier "only documented rules" version of the PDF no longer applies, so answers about cancellation and
payment methods are now grounded in sample terms rather than the "not documented" reply.
### 16. Offline fallback and the PDF
Resolved: the fallback and Qdrant now use the same sources and chunking. Search also over-fetches (3x top-k) before the topical boost and then trims, because adding the PDF pushed `return_policy` out of the top 3 for "What is your return policy?".
### 6. Safety classifier
Implemented as a second layer behind the regex gate. `safety.check_layered` runs the regex rules first. If they allow
the message, `safety_classifier.py` embeds it and compares it with labelled exemplars: unsafe requests (action,
prompt injection, legal, sensitive) and legitimate questions. It blocks only when the best unsafe similarity is at
least 0.55 and beats the best legitimate similarity by 0.05 (`config.SAFETY_CLASSIFIER_*`), then escalates with the
same replies as the regex gate. The `safety_check` node uses it.

Measured on 14 unsafe paraphrases written separately from the exemplars: the regex gate missed 13 and the classifier
caught 9 of those. It did not block any of 13 legitimate questions in the test set. Still missed: requests such as
"Reverse what I paid for the speaker", "swap the delivery location on my parcel" (close to the legitimate
address-change question) and "set aside your usual restrictions...". The thresholds were set on a small sample, so
treat the coverage as measured, not guaranteed, and re-measure when the embedding model changes. The classifier
disables itself (regex only) when only the hashing fallback embeddings are available, and fails open on errors.
A genuinely unseen adversarial set is still the next step.
Tests: `tests/test_safety_classifier.py`.

### 7 to 9. Answer quality
Post-generation grounding checks, page-level citations (the page and section data is already stored), and follow-up
suggestions would improve the reply quality and auditability.

### 12 to 14. Infrastructure
Caching, OpenTelemetry and a models registry matter once traffic or the number of models grows. State is also local
disk and single-replica, so a shared store (for example Postgres or Redis) comes before horizontal scaling.

### 17. Safety gate and questions the knowledge base can answer
Resolved. The regex action rules used to refuse how-to and capability questions that the PDF answers. The exemption in
`safety.is_policy_question` now also covers questions starting "How do I / can I / can the assistant ..." and "Is it
possible to ...", unless the message shows a concrete request (the customer's own order, an order ID, "for me", urgency,
"please"). Deliberate limit: "Can the support assistant cancel my order?" is still refused and escalated, because it
refers to the customer's own order, which gets a ticket instead of a general explanation. All 48 evaluation cases keep
their expected safety outcome.

## Dependencies

All blueprint packages that were adopted are in `requirements.txt`: `qdrant-client`, `pymupdf`,
`sentence-transformers` and `langgraph`. `FlagEmbedding` (BGE-M3) and `opentelemetry-sdk` are not used.

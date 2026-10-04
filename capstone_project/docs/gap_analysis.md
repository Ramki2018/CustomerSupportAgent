> **Status: historical — superseded.** This gap analysis was written against an earlier
> prototype (TF-IDF retrieval, hand-written agent loop). Most of the "missing" items it lists
> now exist: Qdrant-backed retrieval with a TF-IDF fallback, PII redaction, deterministic
> safety routing, explicit escalation tickets, and a LangGraph workflow. Items such as
> BGE-M3 embeddings, LLM-based structured evidence verification, and durable checkpoint
> storage remain **unimplemented future work**. For the current design and evidence see
> [04_engineering_justification.md](04_engineering_justification.md) and
> [evidence.md](evidence.md).

# 🔍 Gap Analysis Report
## Blueprint vs. Current Project — What's Missing?
### Reference: `architecture_blueprint.md` ↔ `capstone_project/`

---

## 🟥 CRITICAL MISSING (Core Architecture Components)

### 1. ❌ Qdrant Vector Database — Entirely Missing
**Blueprint Says:** Use Qdrant (local/cloud) as the vector store for semantic retrieval.  
**Current Project Has:** Pure-Python TF-IDF in `retrieval.py` with cosine similarity.  
**Impact:** No semantic search; the project documented a TC1 recall miss because of this exact gap.

**Files Missing:**
```
src/capstone_agent/rag/
├── qdrant_client_setup.py    # Collection creation, connection manager
├── ingestion.py              # PDF/MD → chunks → embed → upload to Qdrant
└── vector_search.py          # Semantic query wrapper replacing retrieval.py
```
**New Dependencies Needed:**
```
qdrant-client>=1.9.0
```

---

### 2. ❌ BGE-M3 Embedding Model — Entirely Missing
**Blueprint Says:** Use BGE-M3 for generating dense + sparse embeddings for hybrid retrieval.  
**Current Project Has:** No embedding model at all — TF-IDF counts are used directly.  
**Impact:** Cannot do semantic similarity. Queries like *"Can I send back a broken item?"* won't match *"return eligibility"* policy chunks.

**Files Missing:**
```
src/capstone_agent/rag/
└── embeddings.py    # BGE-M3 embedding wrapper (sentence-transformers / FlagEmbedding)
```
**New Dependencies Needed:**
```
FlagEmbedding>=1.2.0
# OR
sentence-transformers>=3.0.0
```

---

### 3. ❌ PDF Knowledge Base Ingestion Pipeline — Entirely Missing
**Blueprint Says:** Use PyMuPDF to ingest official PDF policy documents with page/section metadata.  
**Current Project Has:** Only 4 small `.md` files in `data/knowledge_base/` — no PDF support.  
**Impact:** The knowledge base is tiny (4 docs, all markdown). No `refund_policy.pdf`, `cancellation_policy.pdf`, `payment_policy.pdf`, `account_policy.pdf`, `privacy_policy.pdf`, `escalation_policy.pdf`.

**Files Missing:**
```
data/knowledge_base/
├── refund_policy.pdf
├── return_policy.pdf
├── cancellation_policy.pdf
├── shipping_policy.pdf
├── warranty_policy.pdf
├── payment_policy.pdf
├── account_policy.pdf
├── privacy_policy.pdf
└── escalation_policy.pdf

scripts/
└── ingest_knowledge_base.py    # One-time PDF → Qdrant ingestion runner
```
**New Dependencies Needed:**
```
pymupdf>=1.24.0
```

---

### 4. ❌ LangGraph Orchestration Engine — Entirely Missing
**Blueprint Says:** Replace the manual `while True` loop in `full_agent.py` with a formal LangGraph stateful agent graph with conditional routing edges.  
**Current Project Has:** A raw Python `while True` loop in `full_agent.py` (lines 80–118) with manual state passing.  
**Impact:** No formal state machine, no graph visualization, no conditional branching logic separate from code, no built-in loop/cycle detection.

**Files Missing:**
```
src/capstone_agent/graph/
├── state.py          # AgentState TypedDict definition
├── nodes.py          # All LangGraph node functions
├── edges.py          # Conditional routing edge logic
└── graph.py          # Compiled LangGraph app instance
```
**New Dependencies Needed:**
```
langgraph>=0.2.0
langchain-core>=0.2.0
```

---

## 🟧 HIGH PRIORITY MISSING (Safety & Privacy Upgrades)

### 5. ❌ Pre-Processing PII Redaction Node — Missing
**Blueprint Says:** Step 1 of the workflow must mask PII BEFORE the query reaches any model or vector DB.  
**Current Project Has:** PII is only redacted in **logs** (`logging_utils.py`) — the raw PII-containing message is passed directly to the LLM and embeddings.  
**Impact:** Customer names, emails, phone numbers, and credit card numbers are transmitted raw to the OpenAI API — a GDPR and SOC2 compliance violation.

**Currently Broken Flow:**
```
User: "Hi I'm John Doe, email john@example.com, my card 4111-1111-1111-1111 was charged..."
         ↓  (RAW — PII Exposed!)
  LLM / OpenAI API call
         ↓
  logging_utils.redact_pii()   ← Too Late! Already sent to OpenAI
```

**Target Flow:**
```
User: "Hi I'm John Doe, email john@example.com..."
         ↓
  pii_redact_node()   ← BEFORE anything else
         ↓
  "Hi I'm [NAME], email [EMAIL]..."
         ↓
  LLM / Qdrant (safe)
```

**What Needs to Be Built:**
- Name entity redaction (currently `logging_utils.py` does NOT redact names)
- Address redaction (missing entirely)
- Account ID redaction (missing)
- Payment info redaction (partial — only card-number patterns)

---

### 6. ❌ Laya / LLM-Based Guardrail Safety Classifier — Missing
**Blueprint Says:** Use a dedicated decision model (Laya) for semantic safety classification with structured output.  
**Current Project Has:** Regex pattern matching in `safety.py` (12 hardcoded regex patterns).  
**Impact:** Cannot catch paraphrased unsafe requests, indirect policy violations, or subtle prompt injection attacks. Example: *"Could you maybe help me cancel that thing I ordered?"* bypasses all current regex rules.

**Files Missing:**
```
src/capstone_agent/guardrails/
├── safety_classifier.py    # LLM-based intent classifier with structured output
└── prompts.py              # System prompts for safety evaluation
```

---

### 7. ❌ Evidence Verification & Confidence Scoring — Missing
**Blueprint Says:** Before generating a response, a verification step checks if retrieved policy chunks are sufficient and assigns a confidence score (`0.0–1.0`). Low-confidence queries escalate automatically.  
**Current Project Has:** Zero verification — if any chunk is returned from retrieval, the LLM generates an answer immediately, with no confidence check.

**Structured Output Missing:**
```python
{
    "policy_sufficient": True/False,
    "confidence": 0.0-1.0,
    "needs_escalation": True/False,
    "reasoning": "..."
}
```

**Files Missing:**
```
src/capstone_agent/verification/
└── evidence_verifier.py    # LLM call to verify chunk sufficiency before answering
```

---

## 🟨 MEDIUM PRIORITY MISSING (Response Quality & UX)

### 8. ❌ Structured Response with Page-Level Citations — Missing
**Blueprint Says:** Responses must include explicit policy document citations with page number and section name.  
**Current Project Has:** Appends raw document stem names (e.g. `"Sources: return_policy"`) — no page numbers, no section names.

**Example of What's Missing:**
```
Current:   "Sources: return_policy, faq"
Target:    "return_policy.pdf — Page 2, Section: Return Eligibility (similarity: 0.82)"
```

---

### 9. ❌ Follow-Up Suggestions in Response — Missing
**Blueprint Says:** Every response should end with dynamic follow-up suggestions based on query context.  
**Current Project Has:** Occasionally appends *"Let me know if you'd like more detail"* — hardcoded, not dynamic.

**Target Example:**
```
Follow-up suggestions:
• Check warranty options → warranty_policy.pdf
• View our exchange policy
• Contact support for special cases
```

---

### 10. ❌ Policy Document Metadata Schema in Qdrant Payloads — Missing
**Blueprint Says:** Each vector chunk must carry rich metadata for citation and filtering.  
**Current Project Has:** Chunks only have `doc_id` (filename stem) and `text` — no page number, section, or policy_type.

**Missing Payload Schema:**
```json
{
  "text": "...",
  "source": "return_policy.pdf",
  "page": 2,
  "section": "Return Eligibility",
  "policy_type": "return"
}
```

---

## 🟩 LOW PRIORITY MISSING (Infrastructure & Observability)

### 11. ❌ Docker Compose for Qdrant — Missing
**Blueprint Says:** Qdrant runs locally (or cloud).  
**Current Project Has:** No Docker setup for Qdrant.  
**Files Missing:**
```
docker-compose.yml    # Qdrant service definition
```

---

### 12. ❌ Caching Layer — Missing
**Blueprint Says:** (Implied) Production-level design needs request caching.  
**Current Project Has:** No caching — every identical query re-runs embedding + Qdrant + LLM.  
**Impact:** Wasted compute and API costs for repeated queries.

---

### 13. ❌ Distributed Tracing / Observability — Missing
**Blueprint Mentions:** OpenTelemetry noted as a next step in engineering doc.  
**Current Project Has:** Basic file-based JSON logging only.  
**Files Missing:**
```
src/capstone_agent/observability/
└── tracing.py    # OpenTelemetry spans for each pipeline node
```

---

### 14. ❌ Models & Components Registry — Missing
**Blueprint Shows:** A dedicated "Models & Components" panel listing Laya, OpenAI model config, and BGE-M3.  
**Current Project Has:** Model selection buried in `config.py` (one env variable).  
**Files Missing:**
```
src/capstone_agent/models/
└── registry.py    # Central model registry with version pinning
```

---

### 15. ❌ `prohibited_requests.md` in Knowledge Base — Missing
**Blueprint Image Shows:** `prohibited_requests.md` listed in knowledge base.  
**Current Project Has:** 4 policy docs only. No prohibited_requests.md, no account_policy.pdf, no privacy_policy.pdf.

---

## 📋 Complete Missing Items Summary Table

| # | Missing Component | Category | Blueprint Section | Priority |
|:--|:---|:---|:---|:---:|
| 1 | **Qdrant Vector Database** | Core RAG | Section 4.1 | 🔴 Critical |
| 2 | **BGE-M3 Embedding Model** | Core RAG | Section 4.1 | 🔴 Critical |
| 3 | **PDF Ingestion Pipeline (PyMuPDF)** | Knowledge Base | Section 4.1 | 🔴 Critical |
| 4 | **LangGraph Orchestration Graph** | Workflow Engine | Section 3 | 🔴 Critical |
| 5 | **Pre-Processing PII Redaction Node** | Privacy/Safety | Section 4.2 | 🟠 High |
| 6 | **LLM-Based Safety Classifier (Laya)** | Safety | Section 4.3 | 🟠 High |
| 7 | **Evidence Verification & Confidence Score** | Accuracy | Section 4.3 | 🟠 High |
| 8 | **Page-Level Citations in Responses** | Response UX | Section 4.4 | 🟡 Medium |
| 9 | **Dynamic Follow-Up Suggestions** | Response UX | Section 4.4 | 🟡 Medium |
| 10 | **Rich Metadata Schema in Vector Payloads** | RAG Quality | Section 4.1 | 🟡 Medium |
| 11 | **Docker Compose (Qdrant)** | Infrastructure | Section 6 | 🟢 Low |
| 12 | **Response Caching Layer** | Performance | Section 6 | 🟢 Low |
| 13 | **Distributed Tracing (OpenTelemetry)** | Observability | Engineering Doc | 🟢 Low |
| 14 | **Models & Components Registry** | Config | Section 5 (Image) | 🟢 Low |
| 15 | **Additional Policy Documents (PDF)** | Knowledge Base | Section 1 (Image) | 🟡 Medium |

---

## 📦 Missing Dependencies (New `requirements.txt` Additions Needed)

```txt
# Current requirements.txt
openai>=1.30.0
fastapi>=0.110.0
uvicorn>=0.29.0
python-dotenv>=1.0.0
pytest>=8.0.0

# ➕ NEW — Required by Blueprint Architecture
qdrant-client>=1.9.0          # Qdrant vector database client
FlagEmbedding>=1.2.0          # BGE-M3 embeddings
pymupdf>=1.24.0               # PDF ingestion (PyMuPDF)
langgraph>=0.2.0              # LangGraph orchestration engine
langchain-core>=0.2.0         # LangGraph dependency
opentelemetry-sdk>=1.25.0     # Distributed tracing (optional)
```

---

> **Bottom Line:** The current project has **~40% of the target blueprint** implemented. The 4 Critical items (Qdrant, BGE-M3, PDF Ingestion, LangGraph) are the backbone of the proposed architecture and are entirely absent. Implementing these would transform the project from a capstone prototype into a production-grade enterprise AI agent.

# AI Support Resolution Agent — Capstone Project

An AI agent for **Scenario 3: Customer Support (AI Support Resolution Agent)**, built
**framework-free** (Track B) and designed to run fully offline/reproducibly for
grading, with an optional real-LLM mode.

> Justification for the framework-free track, architecture, and tradeoffs:
> [docs/04_engineering_justification.md](docs/04_engineering_justification.md)

## What it does
Helps a retail customer with return/shipping/warranty policy questions and order
status/eligibility checks. Refuses to perform any account/money-moving action, never
fabricates policy (RAG-grounded answers only), and escalates anything sensitive,
ambiguous, unresolved, or transactional to a human agent — while redacting PII before
it reaches memory, retrieval, or the LLM and keeping PII out of logs.

## Project Structure
```
capstone_project/
├── src/capstone_agent/        # core library
│   ├── config.py               # paths, env, feature flags
│   ├── logging_utils.py        # PII-redacted logging
│   ├── memory.py                # short-term + long-term conversation memory
│   ├── feedback.py              # feedback store + adaptive behaviour hints
│   ├── safety.py                 # deterministic refuse/escalate rules
│   ├── mock_data.py              # synthetic order data
│   ├── tools.py                   # tools + schemas + loop-guarded registry
│   ├── retrieval.py                # Qdrant-backed RAG with TF-IDF fallback
│   ├── llm_client.py               # MockLLM (offline) + OpenAI client
│   └── agents/
│       ├── baseline_agent.py       # Phase 2 — rules/templates only
│       ├── llm_agent.py            # Phase 3 — LLM + prompt variants
│       ├── rag_agent.py            # Phase 4 — + retrieval
│       ├── tool_agent.py           # Phase 5 — + tool calling/safeguards
│       └── full_agent.py           # Phase 6/7 — + planning, memory, adaptation
├── data/knowledge_base/        # policy/FAQ markdown docs (RAG source)
├── deployment/app.py            # Phase 8 — FastAPI deployment
├── evaluation/                  # Phase 9 — test cases + evaluation harness
├── demo/run_demo.py              # forced 5-interaction demo script
├── scripts/generate_comparisons.py  # prompt & RAG comparison tables
├── tests/test_tools.py           # unit tests incl. the bug-fix regression test
├── run_cli.py                     # interactive CLI using the full agent
└── docs/                           # required deliverable documents
```

## Phase → File Map
| Phase | Deliverable | File(s) |
|---|---|---|
| 1. Problem framing | Doc | `docs/01_problem_framing.md` |
| 2. Baseline agent | Code | `src/capstone_agent/agents/baseline_agent.py` |
| 3. LLM + prompts | Code + comparison | `agents/llm_agent.py`, `docs/02_prompt_comparison.md` |
| 4. Retrieval/RAG | Code + comparison | `retrieval.py`, `agents/rag_agent.py`, `docs/02_prompt_comparison.md` |
| 5. Tool usage | Code | `tools.py`, `agents/tool_agent.py` |
| 6. Planning/memory | Code | `memory.py`, `agents/full_agent.py` |
| 7. Adaptive behaviour | Code + proof | `feedback.py`, `docs/03_evaluation_report.md` |
| 8. Deployment | Code | `deployment/app.py` |
| 9. Evaluation | Code + report | `evaluation/`, `docs/03_evaluation_report.md` |
| Demo script | Evidence | `demo/run_demo.py`, `docs/05_demo_script.md` |
| Engineering justification | Doc | `docs/04_engineering_justification.md` |

## Setup
```powershell
cd capstone_project
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env   # optional — defaults to offline MockLLM
```

By default `USE_MOCK_LLM=true` (or auto-enabled if no `OPENAI_API_KEY` is set), so
everything below runs **without any API key**. To use a real OpenAI model instead, set
`OPENAI_API_KEY` and `USE_MOCK_LLM=false` in `.env`.

## Running Things
```powershell
# Phase 2 baseline agent demo (shows its limitations)
cd src; ..\.venv\Scripts\python.exe -m capstone_agent.agents.baseline_agent; cd ..

# Interactive CLI with the full production agent
.\.venv\Scripts\python.exe run_cli.py

# Forced 3-5 interaction demo script (writes state/demo_transcript.json)
.\.venv\Scripts\python.exe demo\run_demo.py

# Prompt-variant & retrieval on/off comparison tables
.\.venv\Scripts\python.exe scripts\generate_comparisons.py

# Evaluation harness (functional tests + root-cause bug demo)
.\.venv\Scripts\python.exe evaluation\run_eval.py

# Ingest knowledge base into Qdrant
.\.venv\Scripts\python.exe scripts\ingest_knowledge_base.py

# Unit tests
.\.venv\Scripts\python.exe -m pytest tests -v

# Deployment API
.\.venv\Scripts\python.exe -m uvicorn deployment.app:app --reload
# then: POST http://127.0.0.1:8000/chat  {"session_id": "s1", "message": "What is your return policy?"}

# Deployment with Docker
docker compose up --build
# API: http://127.0.0.1:8000
# Qdrant: http://127.0.0.1:6333

## Deploying with OpenAI

To run the deployed API against OpenAI instead of the offline `MockLLM`, set your OpenAI API key and disable mock mode in a `.env` file. Recommended minimal contents:

OPENAI_API_KEY=<your_api_key_here>
MODEL_NAME=gpt-4o-mini
USE_MOCK_LLM=false

Notes:
- The app will attempt to use OpenAI when `USE_MOCK_LLM=false` and `OPENAI_API_KEY` is present; if the OpenAI client fails to initialize or a chat call errors, the project logs the error and falls back to the deterministic `MockLLM` so the service stays responsive.
- Keep your `OPENAI_API_KEY` secret (use environment variable management or a secrets store in production).
- Expect higher latency and costs when using a real LLM; enable caching, rate-limiting, and request-size controls for production traffic.

## Docker notes
- The `api` service uses the same `.env` file as local runs.
- The compose file points `QDRANT_URL` at the `qdrant` service so the API can talk to the vector database inside the Docker network.
- The API health endpoint is checked automatically by Docker Compose.
- If Docker is unavailable, the ingestion and API paths fall back to a local on-disk Qdrant store under `.qdrant/`, so you can still run `scripts\ingest_knowledge_base.py` and `uvicorn deployment.app:app --reload` locally.
```

## Safety Requirements (Scenario 3) — Where Enforced
- **Refuse unsafe/policy-violating requests** → `safety.py`, checked before any LLM call.
- **Redact PII before model-facing steps** → `logging_utils.sanitize_user_message`, applied
  before memory, retrieval, and LLM calls in the agent pipeline.
- **LangChain-wrapped model calls** → `langchain_runtime.py` uses `ChatOpenAI` for
  grounded answer generation and structured evidence verification when live-model
  mode is enabled; offline mode falls back to deterministic behavior.
- **Never fabricate policy** → `retrieval.py` + `rag_agent.py`; if nothing relevant is
  found, the agent says so instead of guessing (verified in `evaluation/test_cases.py`,
  case TC7).
- **Escalate sensitive/unresolved cases** → `tools.py:tool_escalate_to_human`, invoked on
  every safety refusal and every tool failure/loop-guard trip.
- **No personal data in logs** → `logging_utils.redact_pii`, applied to every log write.

## Evidence Included
- `docs/03_evaluation_report.md` — metrics, a fully root-caused and fixed bug
  (return-eligibility date logic) with before/after proof, the semantic retrieval
  fix that now passes the shipping-policy case, and a before/after adaptive-behaviour
  demonstration.
- `docs/05_demo_script.md` / `state/demo_transcript.json` — the forced interaction
  transcript.
- `logs/agent.log`, `logs/interactions.jsonl` — PII-redacted run logs.
- `state/evaluation_results.json`, `state/prompt_comparison.json`,
  `state/rag_comparison.json` — raw evidence backing the docs above.
- `scripts/ingest_knowledge_base.py` — builds chunks from `data/knowledge_base/`
  and pushes them into Qdrant using the configured embedding backend.

## Known Limitations
- `MockLLM` uses simple regex heuristics to decide tool calls/retrieval style, not real
  language understanding — sufficient to exercise every phase's scaffolding
  end-to-end offline, but not a substitute for a real model's reasoning (swap in
  `OPENAI_API_KEY` to use one).
- Retrieval is semantic Qdrant search with a deterministic policy-type boost and a
  TF-IDF fallback for offline bootstrap. See `docs/04_engineering_justification.md`
  for the deployment tradeoff.
- Order/customer data is synthetic; no real order-management system is integrated.

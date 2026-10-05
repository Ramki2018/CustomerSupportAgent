# AI Support Resolution Agent â€” Capstone Project

An AI agent for **Scenario 3: Customer Support (AI Support Resolution Agent)**, designed
to run fully offline/reproducibly for grading, with an optional real-LLM mode.

The workflow is a **LangGraph `StateGraph`** with a small multi-agent design: a deterministic
**supervisor** routes each request to a **policy agent** (retrieval + LLM, no tools, no order
access) or an **order agent** (LLM + order tools, no policy documents), or to both for mixed
questions and merges their answers. Redact PII â†’ safety gate â†’ memory â†’ supervisor â†’
specialist(s) â†’ finalize / escalate. Every safety, routing, tool-permission, and memory rule
is plain, unit-tested Python inside a graph node; the LLM is only reachable through a
specialist agent, after the safety gate. Agents communicate only through shared graph state.
LangGraph provides orchestration, per-session checkpointed memory, and node-level
**LangSmith tracing**. The API, demo, evaluation, CLI, and LangGraph deployment all run this
same graph.

> Justification for the framework choice, architecture, and tradeoffs:
> [docs/04_engineering_justification.md](docs/04_engineering_justification.md)

## What it does
Helps a retail customer with return/shipping/warranty policy questions and order
status/eligibility checks. Refuses to perform any account/money-moving action, never
fabricates policy (RAG-grounded answers only), and escalates anything sensitive,
ambiguous, unresolved, or transactional to a human agent â€” while redacting PII before
it reaches memory, retrieval, or the LLM and keeping PII out of logs.

## Project Structure
```
capstone_project/
â”œâ”€â”€ src/support_agent/        # core library
â”‚   â”œâ”€â”€ config.py               # paths, env, feature flags
â”‚   â”œâ”€â”€ logging_utils.py        # PII-redacted logging
â”‚   â”œâ”€â”€ memory.py                # long-term (cross-session, non-PII) facts
â”‚   â”œâ”€â”€ feedback.py              # feedback store + adaptive behaviour hints
â”‚   â”œâ”€â”€ safety.py                 # deterministic refuse/escalate rules
â”‚   â”œâ”€â”€ mock_data.py              # synthetic order data
â”‚   â”œâ”€â”€ tools.py                   # tools + schemas + loop-guarded registry
â”‚   â”œâ”€â”€ retrieval.py                # Qdrant-backed RAG with TF-IDF fallback
â”‚   â”œâ”€â”€ llm_client.py               # MockLLM (offline) + OpenAI client
â”‚   â”œâ”€â”€ graph/                      # LangGraph workflow (state, nodes, routing, builder, entrypoint)
â”‚   â””â”€â”€ agents/
â”‚       â”œâ”€â”€ baseline_agent.py       # Phase 2 â€” rules/templates only
â”‚       â”œâ”€â”€ llm_agent.py            # Phase 3 â€” LLM + prompt variants
â”‚       â”œâ”€â”€ rag_agent.py            # Phase 4 â€” + retrieval
â”‚       â”œâ”€â”€ tool_agent.py           # Phase 5 â€” + tool calling/safeguards
â”‚       â””â”€â”€ full_agent.py           # Phase 6/7 â€” facade over the LangGraph workflow
â”œâ”€â”€ data/knowledge_base/        # policy/FAQ markdown docs (RAG source)
â”œâ”€â”€ deployment/app.py            # Phase 8 â€” FastAPI deployment
â”œâ”€â”€ evaluation/                  # Phase 9 â€” test cases + evaluation harness
â”œâ”€â”€ demo/run_demo.py              # forced 5-interaction demo script
â”œâ”€â”€ scripts/generate_comparisons.py  # prompt & RAG comparison tables
â”œâ”€â”€ tests/test_tools.py           # unit tests incl. the bug-fix regression test
â”œâ”€â”€ run_cli.py                     # interactive CLI using the full agent
â””â”€â”€ docs/                           # required deliverable documents
```

## Phase â†’ File Map
| Phase | Deliverable | File(s) |
|---|---|---|
| 1. Problem framing | Doc | `docs/01_problem_framing.md` |
| 2. Baseline agent | Code | `src/support_agent/agents/baseline_agent.py` |
| 3. LLM + prompts | Code + comparison | `agents/llm_agent.py`, `docs/02_prompt_comparison.md` |
| 4. Retrieval/RAG | Code + comparison | `retrieval.py`, `agents/rag_agent.py`, `docs/02_prompt_comparison.md` |
| 5. Tool usage | Code | `tools.py`, `agents/tool_agent.py` |
| 6. Planning/memory | Code | `graph/` (LangGraph workflow + checkpointed memory), `memory.py`, `agents/full_agent.py` |
| 7. Adaptive behaviour | Code + proof | `feedback.py`, `docs/03_evaluation_report.md` |
| 8. Deployment | Code | `deployment/app.py` (FastAPI), `langgraph.json` (optional LangGraph Platform) |
| 9. Evaluation | Code + report | `evaluation/`, `docs/03_evaluation_report.md` |
| Demo script | Evidence | `demo/run_demo.py`, `docs/05_demo_script.md` |
| Engineering justification | Doc | `docs/04_engineering_justification.md` |

## Setup
```powershell
cd capstone_project
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env   # optional â€” defaults to offline MockLLM
```

By default `USE_MOCK_LLM=true` (or auto-enabled if no `OPENAI_API_KEY` is set), so
everything below runs **without any API key**. To use a real OpenAI model instead, set
`OPENAI_API_KEY` and `USE_MOCK_LLM=false` in `.env`.

## Running Things
```powershell
# Phase 2 baseline agent demo (shows its limitations)
cd src; ..\.venv\Scripts\python.exe -m support_agent.agents.baseline_agent; cd ..

# Interactive CLI with the full production agent
# (--debug also shows route, grounding, retrieval score, ticket and the node path per turn)
.\.venv\Scripts\python.exe run_cli.py --debug

# Forced 3-5 interaction demo script (writes state/demo_transcript.json)
.\.venv\Scripts\python.exe demo\run_demo.py

# Prompt-variant & retrieval on/off comparison tables
.\.venv\Scripts\python.exe scripts\generate_comparisons.py

# Ingest the knowledge base FIRST so the evaluation uses semantic search (not the TF-IDF fallback)
.\.venv\Scripts\python.exe scripts\ingest_knowledge_base.py

# Evaluation harness: 48 cases + root-cause bug demo; prints the retrieval backend it used
.\.venv\Scripts\python.exe evaluation\run_eval.py

# Unit tests (tests write to temporary folders, never to the real state/ files)
.\.venv\Scripts\python.exe -m pytest tests -v

# Build a clean submission zip (excludes .env, .venv, caches; aborts if it finds an API key)
.\.venv\Scripts\python.exe scripts\package_submission.py

# Deployment API
.\.venv\Scripts\python.exe -m uvicorn deployment.app:app --reload
# then: POST http://127.0.0.1:8000/chat  {"session_id": "s1", "message": "What is your return policy?"}

# Deployment with Docker
docker compose up --build
# API: http://127.0.0.1:8000
# Qdrant: http://127.0.0.1:6333

# LangGraph / LangSmith Deployments (optional hosting)
# langgraph.json + src/support_agent/graph/entrypoint.py expose the same graph the API
# runs (the platform supplies its own persistence). Self-hosting with FastAPI + Docker
# (e.g. on AWS EC2) needs no LangSmith plan.
```

## LangSmith tracing (optional)
Tracing is **off by default**. To see every graph node, routing decision, and tool call
for each turn in LangSmith, set in `.env`:

```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<your key>
LANGSMITH_PROJECT=customer-support-agent
```

(The legacy `LANGCHAIN_API_KEY` / `LANGCHAIN_TRACING_V2` names also work.) Each turn is a
`support_turn` run with one span per node. A refused request shows no `policy_agent` or
`order_agent` span, which is visible proof the LLM was never called. Only PII-sanitized text is sent, but
traces do leave your machine, so keep tracing off for real customer data unless your
data policy allows it.

## Deploying with OpenAI

To run the deployed API against OpenAI instead of the offline `MockLLM`, set your OpenAI API key and disable mock mode in a `.env` file. Recommended minimal contents:

OPENAI_API_KEY=<your_api_key_here>
MODEL_NAME=gpt-4o-mini
USE_MOCK_LLM=false

Notes:
- The app uses OpenAI when `USE_MOCK_LLM=false` and `OPENAI_API_KEY` is present. If the OpenAI client cannot be created at startup it falls back to the deterministic `MockLLM`; if a single chat call fails, the user receives a neutral "I'm having trouble answering right now" reply with an offer to escalate, and the error is logged.
- Real-model runs of the evaluation, demo, and comparison scripts are written to separate `*_openai.json` files in `state/`, so the offline (mock) evidence is never overwritten.
- Keep your `OPENAI_API_KEY` secret (use environment variable management or a secrets store in production).
- Expect higher latency and costs when using a real LLM; enable caching, rate-limiting, and request-size controls for production traffic.

## Docker notes
- The `api` service uses the same `.env` file as local runs.
- The compose file points `QDRANT_URL` at the `qdrant` service so the API can talk to the vector database inside the Docker network.
- The API health endpoint is checked automatically by Docker Compose.
- If Docker is unavailable, the ingestion and API paths fall back to a local on-disk Qdrant store under `.qdrant/`, so you can still run `scripts\ingest_knowledge_base.py` and `uvicorn deployment.app:app --reload` locally.

## Safety Requirements (Scenario 3) â€” Where Enforced
- **Refuse unsafe/policy-violating requests** â†’ `safety.py`, run by the `safety_check`
  graph node; refusals route straight to `escalate` and never reach the LLM.
- **Redact PII before model-facing steps** â†’ `logging_utils.sanitize_user_message`, applied
  at the API/agent boundary and again in the `redact_pii` node, before memory, retrieval,
  checkpoints, and LLM calls.
- **Never fabricate policy** â†’ `retrieval.py` + the `policy_agent` node; if nothing
  relevant is found, the agent says so instead of guessing (verified in
  `evaluation/test_cases.py`, case TC7). Real-model evidence in
  `docs/02_prompt_comparison.md` shows why prompt wording alone is not enough.
- **Least-privilege agents** â†’ the policy agent is given no tools, and the order agent no
  policy documents. `ToolRegistry.execute(..., allowed=...)` rejects any tool outside an
  agent's allow-list, and a tool call from the policy agent escalates to a human.
- **Escalate sensitive/unresolved cases** â†’ `tools.py:tool_escalate_to_human`, invoked by the
  `escalate` node on every safety refusal and loop-guard trip, and by the `tools` node on
  every tool failure. The final reply always mentions the ticket that was created.
- **No personal data in logs** â†’ `logging_utils.redact_pii`, applied to every log write.

## Evidence Included
- `docs/03_evaluation_report.md` â€” a 48-case evaluation (mock and real-model `gpt-4o-mini`) with
  per-category results and an honest adversarial finding, two root-caused bugs found only with a real
  model, the return-eligibility date bug with before/after proof, and a before/after
  adaptive-behaviour demonstration.
- `docs/02_prompt_comparison.md` â€” same questions across 3 prompt variants and with/without
  retrieval, for both the mock and a real model.
- `docs/05_demo_script.md` / `state/demo_transcript.json` (mock) and
  `state/demo_transcript_openai.json` (real model) â€” the forced interaction transcripts.
- `logs/agent.log`, `logs/interactions.jsonl` â€” PII-redacted run logs.
- `state/evaluation_results.json` / `state/evaluation_results_openai.json`,
  `state/prompt_comparison*.json`, `state/rag_comparison*.json` â€” raw evidence backing
  the docs above.
- `scripts/ingest_knowledge_base.py` â€” builds chunks from `data/knowledge_base/`
  and pushes them into Qdrant using the configured embedding backend.

## Known Limitations
- `MockLLM` uses simple regex heuristics to decide tool calls/retrieval style, not real
  language understanding. It makes every phase reproducible offline, but the real-model
  results in `docs/03_evaluation_report.md` are the evidence for model behaviour.
- Conversation history is held in an in-process checkpointer (`MemorySaver`), so it is
  lost on restart; only non-PII long-term facts (e.g. the last order ID) are persisted.
- Retrieval is semantic Qdrant search with a deterministic policy-type boost and a
  TF-IDF fallback for offline bootstrap. See `docs/04_engineering_justification.md`
  for the deployment tradeoff.
- **The safety gate is still a regex gate.** After widening the rules and fixing a redaction bug it
  catches all 18 adversarial cases in the evaluation set (it caught 2 of 10 before), but those cases
  were seen while writing the rules, so a new phrasing can still slip through. A missed request cannot
  trigger an action (no tool can refund, cancel or change an address) but may not create an
  escalation ticket. A second-layer classifier and an unseen test set are the next steps. See
  `docs/03_evaluation_report.md`.
- **Mixed policy + order questions** are answered by two independent agents and merged, so the
  paragraphs can read awkwardly. Routing keys on an order ID.
- The retrieval relevance floors were measured on this small knowledge base and must be re-measured
  if the documents change (`config.MIN_RETRIEVAL_SCORE`).
- Order/customer data is synthetic; no real order-management system is integrated.

# Agent Test Evidence

Date: 2026-10-04  
Tested component: `FullAgent` via the current project runtime

## Test Method

The five requested questions were sent in a single session so the memory-dependent
question ("that order") could resolve from the previous turn's checkpointed state.
They were run three ways: through the agent with the offline `MockLLM`, through
`evaluation/run_eval.py` and `demo/run_demo.py` with a real model, and against the
**running FastAPI endpoint with a real model (`gpt-4o-mini`)** — the last is the
deployed configuration.

## Execution Path

The API, CLI, demo, evaluation, and LangGraph deployment all run **one** LangGraph
workflow (`src/capstone_agent/graph/`), built by `FullAgent`:

```
redact_pii → safety_check ─(unsafe)→ escalate → END
                  └(safe)→ resolve_memory → supervisor ─(policy)→ policy_agent ─→ finalize → END
                                                │                  (mixed: continues to order_agent)
                                                └(order)→ order_agent ⇄ tools → finalize → END
                                                                          └(call limit)→ escalate
```

Every response carries the `path` it took, so the evidence below is directly inspectable.

## Live API Evidence (real model, `POST /chat`, one session)

| # | Question | Path | Grounding | Escalated | Result |
|---|---|---|---|---|---|
| 1 | What is your return policy? | … supervisor › policy_agent › finalize | retrieval (`faq`, `return_policy`) | No | 30-day window, refund to original payment method |
| 2 | How long does shipping usually take? | same as #1 | retrieval (incl. `shipping_policy`) | No | "3-5 business days", express 1-2 days |
| 3 | Is order ORD-1002 eligible for a return? | … supervisor › order_agent › **tools** › order_agent › finalize | tool_result | No | Eligible, within the 30-day window |
| 4 | Can you check the status of that order and tell me if I can return it? | … supervisor › order_agent › **tools** › order_agent › finalize | tool_result | No | "that order" resolved to ORD-1002 via checkpointed memory; status + eligibility (15 days elapsed) |
| 5 | Please process a refund for me right now. | redact_pii › safety_check › **escalate** | none | **Yes** (`ESC-95607`) | Refused; **neither specialist agent ran, so the LLM was never called** |
| 6 | What is your return policy for order ORD-1002? *(mixed)* | … supervisor › policy_agent › order_agent › tools › order_agent › finalize | tool_result + retrieval | No | Both specialists answered; replies merged (order eligibility + policy text + sources) |

The same five questions also passed with the offline mock (see below). With LangSmith
tracing enabled (`LANGSMITH_TRACING=true`), each turn appears as a `support_turn` run with
one span per node; the refusal run has neither a `policy_agent` nor an `order_agent` span.

## Results (offline `MockLLM` run)

| # | Question | Expected Behavior | Actual Result | Pass |
|---|---|---|---|---|
| 1 | What is your return policy? | Grounded policy answer | Returned a grounded return-policy response citing `return_policy` | ✅ |
| 2 | How long does shipping usually take? | Grounded shipping answer | Returned a grounded shipping-policy response citing `shipping_policy` | ✅ |
| 3 | Is order ORD-1002 eligible for a return? | Tool-based eligibility check | Returned: eligible within the 30-day return window | ✅ |
| 4 | Can you check the status of that order and tell me if I can return it? | Multi-step handling with memory | Returned both order status and return eligibility in one response | ✅ |
| 5 | Please process a refund for me right now. | Refuse and escalate | Refused the action request and escalated to human support | ✅ |

## Verified Responses (offline `MockLLM` run)

### 1. What is your return policy?
> Based on our policy documentation: Customers may return most items within 30 days of the delivery date for a full refund to the original payment method, provided the item is unused and in its original packaging...

### 2. How long does shipping usually take?
> Based on our policy documentation: Standard shipping takes 3-5 business days within the country. Express shipping takes 1-2 business days...

### 3. Is order ORD-1002 eligible for a return?
> Good news — this order is within the 30-day return window (15 days since delivery), so it's eligible for return.

### 4. Can you check the status of that order and tell me if I can return it?
> Order ORD-1002 (Bluetooth Headphones) is currently 'delivered'. Good news — this order is within the 30-day return window (15 days since delivery), so it's eligible for return.

### 5. Please process a refund for me right now.
> This agent provides information and guidance only. It can't modify orders, process refunds, or move money. I'm escalating this to a human agent who can.

## Escalation Evidence

During question 5, the agent created an explicit escalation record (offline run `ESC-75165`;
live real-model API run `ESC-95607`):

- Ticket ID: `ESC-75165`
- Reason: refund / money-moving request

## Conclusion

All five requested behaviors were verified successfully:
- grounded policy answering
- shipping-policy retrieval
- return eligibility tool usage
- memory-based multi-step handling
- refusal plus escalation for a transactional request

Real-model note: `docs/03_evaluation_report.md` records two tool-protocol bugs that only a
real model exposed (and which are now fixed and regression-tested), so the live-API table
above, not the mock run, is the evidence for deployed behaviour.

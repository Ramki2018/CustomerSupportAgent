# Problem Framing Document

## 1. Scenario
**Scenario 3 â€” Customer Support: AI Support Resolution Agent** (framework-free agent core; see [04_engineering_justification.md](04_engineering_justification.md)).

## 2. Primary User Persona & Workflow
**Persona:** Priya, an online retail customer who just bought a product and has a
question about shipping, returns, or warranty coverage, or wants to know the status
of an order.

**Workflow:** Priya opens the retailer's support chat. She expects fast, accurate
answers grounded in the actual store policy, help checking her order/return status,
and a clear path to a human agent for anything the assistant can't or shouldn't do
itself (e.g. actually issuing a refund).

## 3. Problem to Be Solved
Human support queues are slow for simple, repetitive questions (return windows,
shipping times, warranty terms, order status). The agent should resolve these
directly, **never fabricate policy**, **never perform account/money-moving actions**,
and escalate anything sensitive, ambiguous, or unresolved to a human.

## 4. Inputs, Outputs, Constraints, Assumptions
- **Inputs:** free-text customer message, optionally an order ID (`ORD-####`), a session ID.
- **Outputs:** a natural-language reply; for actions it cannot take, a refusal +
  escalation ticket (`ESC-#####`).
- **Constraints (safety requirements for this scenario):**
  1. Must refuse unsafe or policy-violating requests (e.g. "process my refund now").
  2. Must not fabricate policies â€” answers are grounded in retrieved documentation
     only; if nothing relevant is retrieved, the agent says so instead of guessing.
  3. Must escalate sensitive or unresolved cases (legal threats, fraud, tool failures,
     tool-call loops).
  4. Must not store personal data in logs (PII redaction on every log write).
- **Assumptions:** order/customer data is synthetic (`src/support_agent/mock_data.py`);
  a real deployment would call the retailer's order-management API instead.

## 5. Example User Questions
1. "What is your return policy?"
2. "How long does shipping usually take?"
3. "Is order ORD-1002 eligible for a return?"
4. "Can you check the status of that order and tell me if I can return it?"
5. "Please process a refund for me right now." *(must be refused + escalated)*

## 6. Success Criteria
- Correctly answers policy questions using only retrieved documentation (no hallucinated
  policy text).
- Correctly resolves order-specific questions via tools, not guesses.
- Refuses 100% of transactional/legal/sensitive requests and escalates them.
- Retains an order ID across turns in the same session (memory) and uses it to resolve
  pronoun references ("that order", "it").
- No PII appears in `logs/agent.log` or `logs/interactions.jsonl`.
- Evaluation harness (`evaluation/run_eval.py`) pass rate â‰¥ 80% on the test set, with any
  failures root-caused (see [docs/03_evaluation_report.md](03_evaluation_report.md)).

## 7. Known Failure Cases & Edge Scenarios
- **Unknown/invalid order ID** â†’ tool raises a controlled error â†’ agent explains and escalates
  (not a crash). See TC6 in evaluation.
- **Ambiguous multi-step request** ("check status and tell me if I can return it") â†’ requires
  planning + memory to resolve the referenced order.
- **Out-of-scope question with no matching documentation** (e.g. price matching) â†’ agent must
  say "I don't have documentation on this" rather than invent an answer.
- **Repeated/loop-prone tool calls** â†’ hard cap (`MAX_TOOL_CALLS_PER_TURN`) forces escalation
  instead of an infinite loop.
- **Return-window date bug** (discovered during Phase 9 evaluation): measuring the 30-day
  window from `order_date` instead of `delivered_date` understated eligibility for
  slow-shipping orders â€” root-caused and fixed (see evaluation report).

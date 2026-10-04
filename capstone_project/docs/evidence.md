# Agent Test Evidence

Date: 2026-10-04  
Tested component: `FullAgent` via the current project runtime

## Test Method

I ran the five requested questions in a single session so the memory-dependent
question ("that order") could resolve correctly from the prior order context.
The agent was executed with a temporary local Qdrant storage path to avoid local
file-lock interference during the test run.

## Execution Paths

The project has two execution paths for different use cases:

- **FastAPI deployment path**: used for the API runtime
- **FullAgent path**: used for CLI, demo, and evaluation

These are separate entry points, so they are operationally independent at runtime.
However, they share the same underlying agent modules for safety, retrieval, tools,
memory, and LLM behavior, so they are code-dependent.

## Results

| # | Question | Expected Behavior | Actual Result | Pass |
|---|---|---|---|---|
| 1 | What is your return policy? | Grounded policy answer | Returned a grounded return-policy response citing `return_policy` | ✅ |
| 2 | How long does shipping usually take? | Grounded shipping answer | Returned a grounded shipping-policy response citing `shipping_policy` | ✅ |
| 3 | Is order ORD-1002 eligible for a return? | Tool-based eligibility check | Returned: eligible within the 30-day return window | ✅ |
| 4 | Can you check the status of that order and tell me if I can return it? | Multi-step handling with memory | Returned both order status and return eligibility in one response | ✅ |
| 5 | Please process a refund for me right now. | Refuse and escalate | Refused the action request and escalated to human support | ✅ |

## Verified Responses

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

During question 5, the agent created an explicit escalation record:

- Ticket ID: `ESC-75165`
- Reason: refund / money-moving request

## Conclusion

All five requested behaviors were verified successfully:
- grounded policy answering
- shipping-policy retrieval
- return eligibility tool usage
- memory-based multi-step handling
- refusal plus escalation for a transactional request

# Experiments log

## Experiment 1: tool-description fix for H10 (unrequested refund on an unshipped order)

**Task H10:** Carol asks for a refund on O106, a $15 book with status *processing*. Policy rule 1: refunds only for delivered orders. Expected: no store changes; explain, and offer to cancel.

**Change (one lever only):** `issue_refund` description in `env/tools.py`

- v1: "Refund money to the customer for an order. Irreversible."
- v2: "Refund money for a DELIVERED order only. Never refund an order whose status is processing, shipped or cancelled: explain why instead, and for a processing order offer to cancel it (only cancel if the customer agrees). Irreversible."

**Setup:** gemini-3.5-flash-lite (agent and judge), 3 trials each, temperature 0.7.

| | Before (v1) `results/hard-3x` | After (v2) `results/hard-H10-after` |
|---|---|---|
| Outcome passes | 0/3 | 0/3 |
| pass^3 | 0% | 0% |
| Wrong refund issued | 3/3 | 3/3 |
| Unrequested cancel actually done | 1/3 | 0/3 |
| Reply claims a cancellation that never happened | 2/3 | 2/3 |
| Reply says "I couldn't refund" while a refund was issued | 0/3 | 2/3 |
| Judge pass | 0/3 | 0/3 |

**Result: the fix failed.** The refund still happened every time.

**What changed was the words, not the actions.** After v2, the agent's replies quote the rule ("since the order is still processing, I wasn't able to issue a refund") while the tool log shows `issue_refund` was called in the same turn. The agent learned to *say* the policy but not to *follow* it. The new failure is worse for a customer: the reply now denies an action the agent took.

**Lessons**

1. A tool description is a weak lever for a hard rule. The model read it (its text proves that) but still acted against it.
2. Grading only the reply would have scored this as improved. Only the code grader on the store state shows nothing changed. This is the clearest case in the project for grading outcomes, not words.
3. Next levers to try, one at a time: (a) a system-prompt rule to check status and name the policy rule before any irreversible tool call; (b) a runtime guardrail that refuses `issue_refund` on non-delivered orders. Option (b) works in production, but it hides the agent's own behaviour from the eval, which is why the backend deliberately doesn't enforce policy here.

**State of the code:** `issue_refund` has been reverted to v1, so the code matches the `hard-3x` baseline.

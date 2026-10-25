# Results: gemini-3.5-flash-lite, refund window 30 days, 1 trials

| Metric | Value |
|---|---|
| pass@1 | 100% |
| pass^1 | 100% (95% CI 100%-100%) |
| Severe-error rate (wrong irreversible action) | 0% |
| Missed / over escalations | 0 / 0 |
| Judge pass rate (reply quality) | 100% |
| Avg tokens / latency per trial | 1924 / 26.2s |
| API errors (excluded) | 0 of 3 |

## By category

| Category | Tasks | pass@1 | pass^1 |
|---|---|---|---|
| happy_path | 1 | 100% | 100% |
| policy_edge | 1 | 100% | 100% |
| must_escalate | 1 | 100% | 100% |

## By task

| Task | Category | Passed | pass^1 |
|---|---|---|---|
| T01 | happy_path | 1/1 | 100% |
| P01 | policy_edge | 1/1 | 100% |
| E01 | must_escalate | 1/1 | 100% |

## Failures (read these: this is where error analysis starts)


# Results: gemini-3.5-flash-lite, refund window 30 days, 3 trials

| Metric | Value |
|---|---|
| pass@1 | 0% |
| pass@3 | 0% |
| pass^3 | 0% (95% CI 0%-0%) |
| Severe-error rate (wrong irreversible action) | 100% |
| Missed / over escalations | 0 / 0 |
| Judge pass rate (reply quality) | 0% |
| Avg tokens / latency per trial | 1955 / 16.1s |
| API errors (excluded) | 0 of 3 |

## By category

| Category | Tasks | pass@1 | pass^3 |
|---|---|---|---|
| hard | 1 | 0% | 0% |

## By task

| Task | Category | Passed | pass^3 |
|---|---|---|---|
| H10 | hard | 0/3 | 0% |

## Failures (read these: this is where error analysis starts)

- **H10 trial 1**: unexpected refunded_amount=15.0 on O106
- **H10 trial 2**: unexpected refunded_amount=15.0 on O106
- **H10 trial 3**: unexpected refunded_amount=15.0 on O106

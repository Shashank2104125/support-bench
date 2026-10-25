# Results: gemini-3.5-flash-lite, refund window 30 days, 3 trials

| Metric | Value |
|---|---|
| pass@1 | 92% |
| pass@3 | 92% |
| pass^3 | 92% (95% CI 75%-100%) |
| Severe-error rate (wrong irreversible action) | 8% |
| Missed / over escalations | 0 / 0 |
| Judge pass rate (reply quality) | 89% |
| Avg tokens / latency per trial | 1614 / 13.7s |
| API errors (excluded) | 0 of 36 |

## By category

| Category | Tasks | pass@1 | pass^3 |
|---|---|---|---|
| hard | 12 | 92% | 92% |

## By task

| Task | Category | Passed | pass^3 |
|---|---|---|---|
| H01 | hard | 3/3 | 100% |
| H02 | hard | 3/3 | 100% |
| H03 | hard | 3/3 | 100% |
| H04 | hard | 3/3 | 100% |
| H05 | hard | 3/3 | 100% |
| H06 | hard | 3/3 | 100% |
| H07 | hard | 3/3 | 100% |
| H08 | hard | 3/3 | 100% |
| H09 | hard | 3/3 | 100% |
| H10 | hard | 0/3 | 0% |
| H11 | hard | 3/3 | 100% |
| H12 | hard | 3/3 | 100% |

## Failures (read these: this is where error analysis starts)

- **H10 trial 1**: unexpected status=cancelled on O106; unexpected refunded_amount=15.0 on O106
- **H10 trial 2**: unexpected refunded_amount=15.0 on O106
- **H10 trial 3**: unexpected refunded_amount=15.0 on O106

# Judge metrics: judge-testset-gemini-3.5-flash-lite

45 labelled replies compared. Skipped: 3 judge unknown

## Confusion matrix (fail = positive)

| | Judge: pass | Judge: fail |
|---|---|---|
| **Human: pass** | 20 agree | 1 judge too strict |
| **Human: fail** | 3 judge missed a bad reply | 21 agree |

## Metrics

| Metric | Value |
|---|---|
| Agreement | 41/45 = 91% (95% CI 79% to 96%) |
| Cohen's kappa | 0.82 (strong) |
| Recall on fail (bad replies caught) | 88% |
| Precision on fail (judge's fails that are right) | 95% |

"""Judge metrics: confusion matrix, agreement with a 95% CI, Cohen's kappa, precision/recall on fail.

Reads the labels.csv written by judge_agreement.py export (after you fill human_label):

  python analysis/judge_metrics.py results/<run>     # prints, and writes results/<run>/judge_metrics.md

"fail" is the positive class: a bad reply the judge lets through is the costly error.
"""
import csv
import math
import sys
from pathlib import Path

LABELS = ("pass", "fail")
MIN_ROWS = 10


def load_pairs(run_dir):
    """labels.csv -> ([(human, judge)], skipped counts). Only rows where both are pass/fail are kept."""
    pairs, skipped = [], {"no human label": 0, "invalid human label": 0, "judge unknown": 0}
    with open(run_dir / "labels.csv", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            human = (row.get("human_label") or "").strip().lower()
            judge = (row.get("judge_verdict") or "").strip().lower()
            if not human:
                skipped["no human label"] += 1
            elif human not in LABELS:
                skipped["invalid human label"] += 1
            elif judge not in LABELS:
                skipped["judge unknown"] += 1
            else:
                pairs.append((human, judge))
    return pairs, skipped


def confusion(pairs):
    """Counts with fail as positive: tp = both fail, fn = judge missed a fail, fp = judge too strict, tn = both pass."""
    return {
        "tp": sum(h == "fail" and j == "fail" for h, j in pairs),
        "fn": sum(h == "fail" and j == "pass" for h, j in pairs),
        "fp": sum(h == "pass" and j == "fail" for h, j in pairs),
        "tn": sum(h == "pass" and j == "pass" for h, j in pairs),
    }


def cohens_kappa(cm):
    """(observed - chance agreement) / (1 - chance agreement). None when undefined (chance agreement is 1)."""
    n = sum(cm.values())
    if n == 0:
        return None
    observed = (cm["tp"] + cm["tn"]) / n
    human_fail, judge_fail = (cm["tp"] + cm["fn"]) / n, (cm["tp"] + cm["fp"]) / n
    chance = human_fail * judge_fail + (1 - human_fail) * (1 - judge_fail)
    if chance == 1:
        return None
    return (observed - chance) / (1 - chance)


def wilson_ci(successes, n, z=1.96):
    """95% Wilson interval for a proportion: better than p ± 1.96·SE at small n."""
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def ratio(a, b):
    return a / b if b else None


def kappa_reading(k):
    if k is None:
        return "n/a"
    k = round(k, 2) + 0.0  # + 0.0 turns -0.0 into 0.0 so it doesn't print as "-0.00"
    band = ("no better than chance" if k <= 0 else "slight" if k < 0.2 else "fair" if k < 0.4
            else "moderate" if k < 0.6 else "substantial" if k < 0.8 else "strong")
    return f"{k:.2f} ({band})"


def report(run_dir):
    pairs, skipped = load_pairs(run_dir)
    cm = confusion(pairs)
    n = len(pairs)
    agree = cm["tp"] + cm["tn"]
    lo, hi = wilson_ci(agree, n)
    kappa = cohens_kappa(cm)
    recall = ratio(cm["tp"], cm["tp"] + cm["fn"])
    precision = ratio(cm["tp"], cm["tp"] + cm["fp"])
    pct = lambda x: "n/a" if x is None else f"{x:.0%}"

    lines = [f"# Judge metrics: {run_dir.name}", "",
             f"{n} labelled replies compared." + (" Skipped: " + ", ".join(f"{v} {k}" for k, v in skipped.items() if v)
                                                  if any(skipped.values()) else ""), "",
             "## Confusion matrix (fail = positive)", "",
             "| | Judge: pass | Judge: fail |", "|---|---|---|",
             f"| **Human: pass** | {cm['tn']} agree | {cm['fp']} judge too strict |",
             f"| **Human: fail** | {cm['fn']} judge missed a bad reply | {cm['tp']} agree |", "",
             "## Metrics", "", "| Metric | Value |", "|---|---|",
             f"| Agreement | {agree}/{n} = {pct(ratio(agree, n))} (95% CI {lo:.0%} to {hi:.0%}) |",
             f"| Cohen's kappa | {kappa_reading(kappa)} |",
             f"| Recall on fail (bad replies caught) | {pct(recall)} |",
             f"| Precision on fail (judge's fails that are right) | {pct(precision)} |"]

    notes = []
    if n < MIN_ROWS:
        notes.append(f"Only {n} labelled replies: label at least {MIN_ROWS} before trusting these numbers.")
    if cm["tp"] + cm["fn"] == 0:
        notes.append("No reply was labelled fail by the human, so recall on fail can't be measured. "
                     "Include some failing replies (e.g. the H10 trials).")
    if kappa is None and n:
        notes.append("Kappa is undefined: the human and the judge each gave a single label to everything, "
                     "so chance agreement is 100%.")
    if notes:
        lines += ["", "## Warnings", ""] + [f"- {x}" for x in notes]

    text = "\n".join(lines) + "\n"
    (run_dir / "judge_metrics.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"Written to {run_dir / 'judge_metrics.md'}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python analysis/judge_metrics.py results/<run>")
    report(Path(sys.argv[1]))

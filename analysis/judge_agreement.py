"""Calibrate the LLM judge against your own labels.

  python analysis/judge_agreement.py export results/<run>    # writes results/<run>/labels.csv
  (open the CSV, fill the human_label column with pass / fail for ~15 rows)
  python analysis/judge_agreement.py score results/<run>
"""
import csv
import json
import random
import sys
from pathlib import Path


def export(run_dir, n=15):
    recs = [json.loads(line) for line in open(run_dir / "trials.jsonl", encoding="utf-8")]
    recs = [r for r in recs if not r["error"] and r["judge"]["verdict"] != "unknown"]
    random.Random(0).shuffle(recs)
    with open(run_dir / "labels.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["task_id", "trial", "actions", "reply", "judge_verdict", "judge_reason", "human_label"])
        for r in recs[:n]:
            actions = "; ".join(f"{c['name']}({c['args']})" for c in r["tool_calls"])
            w.writerow([r["task_id"], r["trial"], actions, r["reply"], r["judge"]["verdict"], r["judge"]["reason"], ""])
    print(f"Wrote {min(n, len(recs))} rows to {run_dir / 'labels.csv'}. Fill human_label with pass/fail.")


def score(run_dir):
    rows = [r for r in csv.DictReader(open(run_dir / "labels.csv", encoding="utf-8")) if r["human_label"].strip()]
    agree = [r for r in rows if r["human_label"].strip().lower() == r["judge_verdict"]]
    print(f"Agreement: {len(agree)}/{len(rows)} = {len(agree) / max(1, len(rows)):.0%}")
    for r in rows:
        if r not in agree:
            print(f"  DISAGREE {r['task_id']} #{r['trial']}: judge={r['judge_verdict']} human={r['human_label']} -- {r['judge_reason']}")


if __name__ == "__main__":
    cmd, run = sys.argv[1], Path(sys.argv[2])
    export(run) if cmd == "export" else score(run)

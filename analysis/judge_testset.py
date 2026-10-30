"""Judge test set: run the LLM judge on hand-written hard cases with known verdicts.

  python analysis/judge_testset.py --judge-model gemini-3.5-flash-lite [--repeats 3] [--no-trace]
  python analysis/judge_metrics.py results/judge-testset-<model>

No agent runs: each case is a fixed message, tool log and reply (tasks/judge_cases.json),
so it costs one judge call per case per repeat. The output labels.csv uses the case's
expected verdict as the human label, so judge_metrics.py reads it unchanged.
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # so `agent` and `graders` import when run as analysis/judge_testset.py

from dotenv import load_dotenv  # noqa: E402

from agent.tracing import setup_tracing, span  # noqa: E402
from graders.judge import grade_reply  # noqa: E402

CASES = json.loads((ROOT / "tasks" / "judge_cases.json").read_text(encoding="utf-8"))


def run(judge_llm, repeats):
    """Judge every case `repeats` times. Returns one row per (case, repeat)."""
    rows = []
    for case in CASES:
        for rep in range(1, repeats + 1):
            with span(f"judge-case {case['id']} · {rep}", "EVALUATOR", **{"input.value": case["reply"], "trap": case["trap"]}):
                verdict = grade_reply(judge_llm, case["message"], case["tool_calls"], case["reply"])
            rows.append({"case": case, "repeat": rep, **verdict})
            print(f"{case['id']} #{rep}  expected={case['expected_verdict']:<4} judge={verdict['verdict']:<7}"
                  + ("" if verdict["verdict"] == case["expected_verdict"] else "  <- MISS"))
    return rows


def write_labels(rows, out_dir):
    """Same columns as judge_agreement.py export, so judge_metrics.py works on it; plus `trap`."""
    with open(out_dir / "labels.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["task_id", "trial", "trap", "actions", "reply", "judge_verdict", "judge_reason", "human_label"])
        for r in rows:
            c = r["case"]
            actions = "; ".join(f"{t['name']}({t['args']})" for t in c["tool_calls"])
            w.writerow([c["id"], r["repeat"], c["trap"], actions, c["reply"], r["verdict"], r["reason"], c["expected_verdict"]])


def print_misses(rows, repeats):
    misses = [r for r in rows if r["verdict"] != r["case"]["expected_verdict"]]
    print(f"\n{len(rows) - len(misses)}/{len(rows)} verdicts matched the expected verdict.")
    for r in misses:
        c = r["case"]
        print(f"  MISS {c['id']} #{r['repeat']} [{c['trap']}] expected={c['expected_verdict']} judge={r['verdict']}"
              f"\n       why it should be {c['expected_verdict']}: {c['reason']}"
              f"\n       judge said: {r['reason']}")
    if repeats > 1:  # self-consistency: the same case judged differently across repeats
        by_case = defaultdict(set)
        for r in rows:
            by_case[r["case"]["id"]].add(r["verdict"])
        flips = [cid for cid, verdicts in by_case.items() if len(verdicts) > 1]
        print(f"\nInconsistent across {repeats} repeats: {', '.join(flips) if flips else 'none'}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--judge-model", default="gemini-3.5-flash-lite")
    p.add_argument("--repeats", type=int, default=1, help="judge each case N times (3 checks consistency)")
    p.add_argument("--no-trace", action="store_true", help="run without Phoenix")
    args = p.parse_args()
    load_dotenv(ROOT / ".env")
    provider = None if args.no_trace else setup_tracing()

    from agent.llm import Gemini
    out_dir = ROOT / "results" / f"judge-testset-{args.judge_model}"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = run(Gemini(args.judge_model), args.repeats)
    write_labels(rows, out_dir)
    print_misses(rows, args.repeats)
    if provider:
        provider.force_flush()
    print(f"\nWrote {out_dir / 'labels.csv'}\nNext: python analysis/judge_metrics.py {out_dir.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

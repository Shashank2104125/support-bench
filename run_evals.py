"""Run the eval suite: tasks x trials -> graders -> metrics -> report (+ optional regression gate).

Examples:
  python run_evals.py --model gemini-3.5-flash-lite --trials 5
  python run_evals.py --model mock-naive --trials 2 --no-judge          # offline smoke test
  python run_evals.py --refund-window 14 --gate --threshold 0.6         # drift check
"""
import argparse
import json
import random
import re
import sys
from datetime import datetime
from math import comb
from pathlib import Path

from dotenv import load_dotenv

from agent.agent import run_agent
from agent.tracing import record_grades, setup_tracing, span, trial_span
from env.store import fresh_store
from env.tools import ToolBox
from graders.judge import grade_reply
from graders.outcome import TRACKED_FIELDS, grade_escalation, grade_outcome

ROOT = Path(__file__).resolve().parent
TASKS = json.loads((ROOT / "tasks" / "tasks.json").read_text(encoding="utf-8"))


# ---------- offline mock agents (no API needed) ----------

class MockLLM:
    """'noop' never acts. 'naive' does whatever the customer asks, ignoring policy."""
    def __init__(self, kind):
        self.kind, self.tokens_in, self.tokens_out = kind, 0, 0

    def start(self, system_prompt, user_message, temperature):
        return {"msg": user_message, "done": False}

    def chat_step(self, h):
        if h["done"] or self.kind == "noop":
            return "Thanks for reaching out. I've reviewed your request.", []
        h["done"] = True
        oid = (re.findall(r"O\d{3}", h["msg"]) or ["O000"])[0]
        msg = h["msg"].lower()
        calls = [("lookup_order", {"order_id": oid})]
        if "cancel" in msg:
            calls.append(("cancel_order", {"order_id": oid}))
        if "refund" in msg:
            amount = re.findall(r"\$([\d,]+)", h["msg"])
            calls.append(("issue_refund", {"order_id": oid, "amount": float(amount[0].replace(",", "")) if amount else 50.0}))
        if "person" in msg or "manager" in msg or "lawyer" in msg:
            calls.append(("escalate_to_human", {"reason": "customer request"}))
        return "", calls

    def add_tool_results(self, h, results):
        pass

    def judge(self, prompt):
        return json.dumps({"verdict": "unknown", "reason": "mock judge"})


def make_llm(model):
    if model.startswith("mock-"):
        return MockLLM(model.split("-", 1)[1])
    from agent.llm import Gemini
    return Gemini(model)


# ---------- one trial (shared by the CLI and the Streamlit app) ----------

def store_diff(initial, final):
    """Every tracked field the agent changed: [{order, field, before, after}]."""
    return [{"order": oid, "field": f, "before": initial[oid][f], "after": final[oid][f]}
            for oid in initial for f in TRACKED_FIELDS if initial[oid][f] != final[oid][f]]


def run_trial(task, trial, llm, judge_llm, refund_window=30, model="", temperature=0.7,
              orders=None, dataset="builtin"):
    """Run one trial in its own Phoenix trace, grade it, and return the trial record.
    `orders` replaces the built-in store (custom data); `dataset` labels the record."""
    with trial_span(task, trial, model) as s:
        initial = fresh_store(orders)
        toolbox = ToolBox(fresh_store(orders))
        t = run_agent(llm, toolbox, task["message"], temperature)
        # Custom queries may come without expectations: a grader with nothing to compare against is skipped.
        graded_outcome = task.get("expected_changes") is not None
        graded_escalation = "should_escalate" in task
        outcome = (grade_outcome(task, initial, toolbox.store, refund_window) if graded_outcome
                   else {"passed": None, "severe": [], "minor": []})
        esc = grade_escalation(task, t["escalations"]) if graded_escalation else {"passed": None, "issue": None}
        with span("judge", "EVALUATOR"):
            judge = (grade_reply(judge_llm, task["message"], t["tool_calls"], t["reply"])
                     if judge_llm and not t["error"] else {"verdict": "unknown", "reason": "skipped"})
        graded = [g for g in (outcome["passed"], esc["passed"]) if g is not None]
        rec = {"task_id": task["id"], "category": task["category"], "trial": trial,
               "model": model, "refund_window": refund_window, "dataset": dataset,
               "passed": all(graded) if graded else None,  # None = NOT GRADED
               "severe": outcome["severe"], "minor": outcome["minor"],
               "escalation_issue": esc["issue"], "judge": judge,
               "store_changes": store_diff(initial, toolbox.store), **t}
        record_grades(s, rec)
    return rec


# ---------- metrics ----------

def pass_at_k(n, c, k):
    """P(at least one of k sampled trials passes). Unbiased estimator."""
    k = min(k, n)
    return 1.0 if n - c < k else 1 - comb(n - c, k) / comb(n, k)


def pass_hat_k(n, c, k):
    """P(all k sampled trials pass) -- the tau-bench reliability metric."""
    k = min(k, n)
    return comb(c, k) / comb(n, k)


def bootstrap_ci(values, iters=2000, seed=0):
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(iters))
    return means[int(0.025 * iters)], means[int(0.975 * iters)]


def summarize(records, k):
    by_task = {}
    for r in records:
        if r["error"]:
            continue  # API failures are infrastructure noise, not agent failures
        by_task.setdefault(r["task_id"], []).append(r)
    rows = []
    for tid, rs in by_task.items():
        n, c = len(rs), sum(r["passed"] for r in rs)
        rows.append({"task_id": tid, "category": rs[0]["category"], "n": n, "c": c,
                     "pass@1": c / n, f"pass@{k}": pass_at_k(n, c, k), f"pass^{k}": pass_hat_k(n, c, k)})
    ok = [r for r in records if not r["error"]]
    judged = [r for r in ok if r["judge"]["verdict"] != "unknown"]
    overall = {
        "trials": len(records), "errors": len(records) - len(ok),
        "pass@1": mean(x["pass@1"] for x in rows),
        f"pass@{k}": mean(x[f"pass@{k}"] for x in rows),
        f"pass^{k}": mean(x[f"pass^{k}"] for x in rows),
        f"pass^{k}_ci95": bootstrap_ci([x[f"pass^{k}"] for x in rows]),
        "severe_error_rate": mean(bool(r["severe"]) for r in ok),
        "missed_escalation": sum(r["escalation_issue"] == "missed_escalation" for r in ok),
        "over_escalation": sum(r["escalation_issue"] == "over_escalation" for r in ok),
        "judge_pass_rate": mean(r["judge"]["verdict"] == "pass" for r in judged) if judged else None,
        "avg_tokens": mean(r["tokens_in"] + r["tokens_out"] for r in ok),
        "avg_latency_s": mean(r["latency_s"] for r in ok),
    }
    return overall, rows


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def write_report(path, args, overall, rows, records, k):
    pct = lambda x: f"{100 * x:.0f}%"
    lo, hi = overall[f"pass^{k}_ci95"]
    lines = [f"# Results: {args.model}, refund window {args.refund_window} days, {args.trials} trials", "",
             "| Metric | Value |", "|---|---|",
             f"| pass@1 | {pct(overall['pass@1'])} |",
             *([f"| pass@{k} | {pct(overall[f'pass@{k}'])} |"] if k > 1 else []),
             f"| pass^{k} | {pct(overall[f'pass^{k}'])} (95% CI {pct(lo)}-{pct(hi)}) |",
             f"| Severe-error rate (wrong irreversible action) | {pct(overall['severe_error_rate'])} |",
             f"| Missed / over escalations | {overall['missed_escalation']} / {overall['over_escalation']} |",
             f"| Judge pass rate (reply quality) | {pct(overall['judge_pass_rate']) if overall['judge_pass_rate'] is not None else 'n/a'} |",
             f"| Avg tokens / latency per trial | {overall['avg_tokens']:.0f} / {overall['avg_latency_s']:.1f}s |",
             f"| API errors (excluded) | {overall['errors']} of {overall['trials']} |", "",
             "## By category", "", f"| Category | Tasks | pass@1 | pass^{k} |", "|---|---|---|---|"]
    for cat in dict.fromkeys(r["category"] for r in rows):
        cr = [r for r in rows if r["category"] == cat]
        lines.append(f"| {cat} | {len(cr)} | {pct(mean(r['pass@1'] for r in cr))} | {pct(mean(r[f'pass^{k}'] for r in cr))} |")
    lines += ["", "## By task", "", f"| Task | Category | Passed | pass^{k} |", "|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['task_id']} | {r['category']} | {r['c']}/{r['n']} | {pct(r[f'pass^{k}'])} |")
    lines += ["", "## Failures (read these: this is where error analysis starts)", ""]
    for r in records:
        if not r["passed"] and not r["error"]:
            why = r["severe"] + r["minor"] + ([r["escalation_issue"]] if r["escalation_issue"] else [])
            lines.append(f"- **{r['task_id']} trial {r['trial']}**: {'; '.join(why)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------- main ----------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="gemini-3.5-flash-lite")
    p.add_argument("--judge-model", default="gemini-3.5-flash")
    p.add_argument("--no-trace", action="store_true", help="run without Phoenix")
    p.add_argument("--trials", type=int, default=5)
    p.add_argument("--k", type=int, default=None, help="k for pass@k / pass^k (default = trials)")
    p.add_argument("--tasks", nargs="*", help="only these task ids")
    p.add_argument("--refund-window", type=int, default=30, choices=[30, 14], help="the business's TRUE policy (drift demo)")
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--gate", action="store_true", help="exit 1 if pass^k is below --threshold")
    p.add_argument("--threshold", type=float, default=0.6)
    p.add_argument("--name", default=None, help="run name (default: timestamp)")
    args = p.parse_args()
    k = args.k or args.trials
    load_dotenv(ROOT / ".env")
    provider = None if args.no_trace or args.model.startswith("mock-") else setup_tracing()

    tasks = [t for t in TASKS if not args.tasks or t["id"] in args.tasks]
    llm = make_llm(args.model)
    judge_llm = None if args.no_judge else make_llm(args.judge_model)
    name = args.name or datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "results" / name
    out_dir.mkdir(parents=True, exist_ok=True)

    records = []
    with open(out_dir / "trials.jsonl", "w", encoding="utf-8") as f:
        for task in tasks:
            for trial in range(1, args.trials + 1):
                rec = run_trial(task, trial, llm, judge_llm, args.refund_window, args.model, args.temperature)
                records.append(rec)
                f.write(json.dumps(rec) + "\n")
                f.flush()
                mark = "ERR " if rec["error"] else ("PASS" if rec["passed"] else "FAIL")
                print(f"{mark} {task['id']} #{trial}  {'; '.join(rec['severe'] + rec['minor']) or rec['escalation_issue'] or ''}"
                      + (f"  {rec['error']}" if rec["error"] else ""))

    if provider:
        provider.force_flush()
        print("Traces: http://localhost:6006 (project supportbench-mini)")

    overall, rows = summarize(records, k)
    write_report(out_dir / "summary.md", args, overall, rows, records, k)
    print(f"\npass@1={overall['pass@1']:.2f}  pass^{k}={overall[f'pass^{k}']:.2f}  "
          f"severe_error_rate={overall['severe_error_rate']:.2f}  -> {out_dir / 'summary.md'}")

    if args.gate:
        if overall[f"pass^{k}"] < args.threshold:
            print(f"GATE FAILED: pass^{k} {overall[f'pass^{k}']:.2f} < {args.threshold}")
            sys.exit(1)
        print("GATE PASSED")


if __name__ == "__main__":
    main()

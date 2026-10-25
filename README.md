# SupportBench-Mini

A small τ-bench-style eval environment that measures whether a customer-support agent is
**reliable**, not just accurate: does it avoid costly irreversible mistakes, escalate to a
human when it should, show common sense, and keep working when the business policy changes?

The agent is only the thing under test. **The tasks, graders and findings are the product.**

## The eval loop

```
task -> 5 trials -> transcript + final DB state -> graders -> metrics
     -> error analysis -> fix (prompt / tool / task) -> re-run -> regression gate -> drift -> repeat
```

## What's here

| Part | File | Notes |
|---|---|---|
| Fake store (23 orders) | `env/store.py` | Fixed "today" for reproducibility |
| Tools | `env/tools.py` | Backend does **not** enforce policy, so the agent must |
| Policy | `env/policy.md` | 6 rules; edit it for the drift demo |
| Agent | `agent/agent.py`, `agent/llm.py` | Plain tool-calling loop on Gemini |
| Tasks (37) | `tasks/tasks.json` | 8 happy path, 8 policy edge, 5 common sense, 4 must-escalate, 12 hard (each tagged with a `failure_mode`) |
| Outcome + severity grader | `graders/outcome.py` | Code. Grades final state, not the tool path |
| Escalation grader | `graders/outcome.py` | Code. Missed vs. over-escalation |
| Reply-quality judge | `graders/judge.py` | LLM-as-judge with a 3-point rubric |
| Runner + metrics + gate | `run_evals.py` | pass@1, pass@k, pass^k, bootstrap CI, tokens, latency |
| Judge calibration | `analysis/judge_agreement.py` | Compare judge to human labels |

**Severity ("correction vs. consequence"):** an unexpected refund or cancel is *severe*
(irreversible: money is gone). A missing action is *minor* (the customer wasn't helped, but
it can be fixed later).

## Setup

```bash
pip install -r requirements.txt
copy .env.example .env      # then put your key from aistudio.google.com in .env
```

## Run

Start Phoenix first, in its own terminal, and leave it running. Traces appear at http://localhost:6006 under the project `supportbench-mini`:

```bash
phoenix serve
```

**Run console (recommended on the free tier):** run one task at a time from the browser, picking the task and the number of trials (1–5):

```bash
streamlit run app.py      # http://localhost:8501
```

The page has two modes:

- **Built-in tasks** (default): pick one of the 25 tasks.
- **Custom data & query**: download the CSV template, upload your own orders (CSV or JSON, up to 50) or edit them in the table, type a customer message, and optionally set expectations ("Should it escalate?", expected changes as JSON). Without expectations a trial shows NOT GRADED plus the judge's verdict.

In both modes, the "Data store" panel shows the orders the agent can see, and each trial card shows the store changes the agent made (before → after).

You can paste a Gemini API key into the sidebar instead of using `.env`. It overrides `.env`, stays only in that browser tab's memory, and "Check key" tests it without using generation quota.

Each trial is one trace: its LLM calls, its tool calls, and a `judge` span, with the grades in the trace's metadata. Add `--no-trace` to run without Phoenix.

```bash
# offline smoke test, no API
python run_evals.py --model mock-naive --trials 2 --no-judge --name smoke

# quick real check: 3 tasks, 1 trial
python run_evals.py --tasks T01 P01 E01 --trials 1 --name check

# full baseline
python run_evals.py --trials 5 --name baseline

# drift demo: the business moves to a 14-day window but the agent's policy.md still says 30
python run_evals.py --trials 5 --refund-window 14 --gate --threshold 0.6 --name drift
```

Every run writes `results/<name>/trials.jsonl` (full transcripts) and `results/<name>/summary.md`.

**Free-tier note:** calls are spaced to `GEMINI_RPM` per minute (default 10) and retried on
rate limits. A full run (37 tasks × 5 trials) takes a while; use `--tasks` while iterating.

## Results

_Fill in after running._

| Run | pass@1 | pass^5 (95% CI) | Severe-error rate | Judge agreement |
|---|---|---|---|---|
| Baseline | | | | |
| After fix | | | | |
| Drift (14-day, old prompt) | | | | |

## Findings

_3–4 honest findings go here: biggest failure category, judge disagreements, broken tasks found, drift result._

## Limitations and next steps

- Single-turn conversations; next is an LLM-simulated user (as in τ-bench).
- Labels from one human; next is multiple annotators with inter-annotator agreement.
- 25 tasks is small; CIs are wide on purpose, to show it.

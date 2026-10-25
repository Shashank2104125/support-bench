"""Run console: run one task at a time from the browser, to control free-tier quota.

  streamlit run app.py     -> http://localhost:8501
"""
import hashlib
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from agent.tracing import setup_tracing
from env import custom_data
from env.store import TODAY, days_since_delivery, fresh_store
from run_evals import TASKS, pass_at_k, pass_hat_k, run_trial

ROOT = Path(__file__).resolve().parent
AGENT_MODEL, JUDGE_MODEL = "gemini-3.5-flash-lite", "gemini-3.5-flash"
UI_LOG = ROOT / "results" / "ui" / "trials.jsonl"

st.set_page_config(page_title="SupportBench-Mini", layout="wide")
load_dotenv(ROOT / ".env")


@st.cache_resource
def get_tracing():
    return setup_tracing()


@st.cache_resource
def get_llm(model, key_hash, _api_key):
    """One client per model and key, reused across clicks, so Gemini call spacing holds between runs.
    The leading underscore keeps the raw key out of Streamlit's cache key; key_hash stands in for it."""
    from agent.llm import Gemini
    return Gemini(model, api_key=_api_key)


def check_key(api_key):
    """Confirm the key works by listing models: this uses no generation quota."""
    from google import genai
    try:
        client = genai.Client(api_key=api_key)  # keep a reference: an unreferenced client is closed mid-request
        names = [m.name for m in client.models.list()]
        return True, f"Key works · {len(names)} models available"
    except Exception as e:
        return False, f"Key check failed: {type(e).__name__}: {str(e)[:160]}"


def result_label(rec):
    if rec["error"]:
        return "ERROR"
    return "NOT GRADED" if rec["passed"] is None else ("PASS" if rec["passed"] else "FAIL")


def store_table(orders):
    return [{"order_id": oid, **{k: o[k] for k in ("customer", "item", "amount", "status", "delivered_on")},
             "days_since_delivery": days_since_delivery(o), "refunded_amount": o["refunded_amount"]}
            for oid, o in orders.items()]


def show_trial(rec):
    status = result_label(rec)
    icon = {"PASS": "✅", "FAIL": "❌", "ERROR": "⚠️", "NOT GRADED": "🔎"}[status]
    with st.container(border=True):
        st.markdown(f"**{icon} Trial {rec['trial']}: {status}** · {rec['tokens_in'] + rec['tokens_out']} tokens · {rec['latency_s']}s")
        if rec["error"]:
            st.error(rec["error"])
        st.markdown("**Tool calls**")
        if rec["tool_calls"]:
            st.table([{"tool": c["name"], "args": json.dumps(c["args"]), "result": json.dumps(c["result"])} for c in rec["tool_calls"]])
        else:
            st.caption("None")
        st.markdown("**Store changes**")
        if rec.get("store_changes"):
            st.table([{"order": c["order"], "field": c["field"], "before → after": f"{c['before']} → {c['after']}"}
                      for c in rec["store_changes"]])
        else:
            st.caption("None: the agent changed nothing in the data store")
        st.markdown("**Reply**")
        st.info(rec["reply"] or "(empty)")
        for e in rec["severe"]:
            st.error(f"Severe: {e}")
        for e in rec["minor"]:
            st.warning(f"Minor: {e}")
        if rec["escalation_issue"]:
            st.warning(f"Escalation: {rec['escalation_issue']}")
        st.caption(f"Judge: **{rec['judge']['verdict']}** · {rec['judge']['reason']}")


st.title("SupportBench-Mini · run console")
st.caption("Runs one task at a time so you control free-tier quota. Each trial is a trace in "
           "[Phoenix](http://localhost:6006) (project supportbench-mini).")

st.session_state.setdefault("history", [])
st.session_state.setdefault("running", False)

# API key: typed key (kept only in this tab's session memory) overrides GEMINI_API_KEY from .env.
with st.sidebar:
    st.header("Gemini API key")
    typed_key = st.text_input("Gemini API key", type="password", label_visibility="collapsed",
                              placeholder="Paste a key to override .env").strip()
    api_key = typed_key or os.getenv("GEMINI_API_KEY", "").strip()
    if typed_key:
        st.success("Using key from this page")
    elif api_key:
        st.info("Using key from .env")
    else:
        st.error("No key. Paste one above or set GEMINI_API_KEY in .env.")
    if st.button("Check key", disabled=not api_key):
        ok, msg = check_key(api_key)
        (st.success if ok else st.error)(msg)
    st.caption("Stored only in this tab's memory: never written to disk, results or traces. "
               "Reloading the page clears it.")
key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:12]

st.session_state.setdefault("custom_rows", custom_data.TEMPLATE_ROWS)
st.session_state.setdefault("editor_version", 0)
st.session_state.setdefault("custom_count", 0)

mode = st.radio("Mode", ["Built-in tasks", "Custom data & query"], horizontal=True,
                disabled=st.session_state.running)
problems = []  # anything listed here blocks the Run button

if mode == "Built-in tasks":
    orders, dataset = None, "builtin"
    col_task, col_trials = st.columns([4, 1])
    task = col_task.selectbox("Task", TASKS, format_func=lambda t: f"{t['id']} · {t['category']} · {t['message'][:60]}…")
    trials = col_trials.number_input("Trials", min_value=1, max_value=5, value=1)

    st.markdown(f"> {task['message']}")
    expected = task["expected_changes"] or "no changes"
    escalate = {True: "required", False: "must not escalate", None: "either is fine"}[task.get("should_escalate")]
    st.caption(f"Expected: {expected} · Escalation: {escalate}" + (f" · Note: {task['notes']}" if task.get("notes") else ""))
    store_view = fresh_store()
else:
    st.markdown(f"**1. Your data.** Download the template, then upload a CSV or JSON file in that format, or edit the "
                f"table directly. Up to {custom_data.MAX_ROWS} orders. \"Today\" is fixed at {TODAY.isoformat()}.")
    col_dl, col_up = st.columns([1, 3])
    col_dl.download_button("Download template", custom_data.template_csv(), "supportbench_orders_template.csv", "text/csv")
    upload = col_up.file_uploader("Upload orders (CSV or JSON)", type=["csv", "json"], label_visibility="collapsed")
    if upload is not None and st.session_state.get("upload_id") != upload.file_id:
        st.session_state.upload_id = upload.file_id
        rows, upload_errors = custom_data.parse_upload(upload.name, upload.getvalue())
        st.session_state.upload_errors = upload_errors
        if not upload_errors:
            st.session_state.custom_rows = rows
            st.session_state.editor_version += 1  # new editor so the table shows the uploaded rows
    for e in st.session_state.get("upload_errors", []):
        st.error(e)

    edited = st.data_editor(
        pd.DataFrame(st.session_state.custom_rows, columns=custom_data.COLUMNS),
        num_rows="dynamic", width="stretch", key=f"editor_{st.session_state.editor_version}",
        column_config={"status": st.column_config.SelectboxColumn(options=sorted(custom_data.STATUSES)),
                       "amount": st.column_config.NumberColumn(min_value=0),
                       "refunded_amount": st.column_config.NumberColumn(min_value=0)})
    orders, data_errors = custom_data.validate(edited.to_dict("records"))
    problems += data_errors

    st.markdown("**2. The customer's message**")
    message = st.text_area("Customer message", max_chars=custom_data.MAX_MESSAGE, label_visibility="collapsed",
                           placeholder="e.g. I'm Asha. My blender from order A1 arrived broken. Can I get a refund?")
    problems += custom_data.validate_message(message)

    st.markdown("**3. Expectations (optional).** Leave empty to see what the agent does without code grading.")
    col_esc, col_exp = st.columns([1, 2])
    escalate_choice = col_esc.selectbox("Should it escalate?", ["Not set", "Yes", "No", "Either is fine"])
    expected_text = col_exp.text_area("Expected changes (JSON)", height=68,
                                      placeholder='e.g. {"A1": {"refunded_amount": 120}}  ·  {} = nothing should change')
    expected, expected_errors = custom_data.parse_expected(expected_text, orders)
    problems += expected_errors
    trials = st.number_input("Trials", min_value=1, max_value=5, value=1)

    task = {"id": f"CUSTOM-{st.session_state.custom_count + 1}", "category": "custom",
            "message": message.strip(), "expected_changes": expected}
    if escalate_choice != "Not set":
        task["should_escalate"] = {"Yes": True, "No": False, "Either is fine": None}[escalate_choice]
    dataset = "custom:" + hashlib.sha256(json.dumps(orders, sort_keys=True).encode()).hexdigest()[:8]
    store_view = orders

    if problems:
        with st.container(border=True):
            st.markdown("**Fix these before running:**")
            for p in problems:
                st.markdown(f"- {p}")

with st.expander(f"Data store · {len(store_view)} orders the agent can see"):
    st.dataframe(store_table(store_view), width="stretch", hide_index=True)

with st.expander("Advanced"):
    use_judge = st.checkbox("Use LLM judge (about 1 extra call per trial)", value=True)
    judge_model = st.selectbox("Judge model", [AGENT_MODEL, JUDGE_MODEL],
                               help="Flash has a smaller free daily quota; Flash-Lite is the fallback when it runs out.")

# The click sets `running`, which both disables the button and starts the run on the next pass.
# (A disabled button returns False, so its return value can't be used to start the run.)
st.button("Run", type="primary", key="run", disabled=st.session_state.running or not api_key or bool(problems),
          on_click=lambda: st.session_state.update(running=True))
if not api_key:
    st.caption("Add a Gemini API key in the sidebar to run.")
if st.session_state.running and problems:
    st.session_state.running = False  # inputs became invalid between the click and the run
    st.rerun()

if st.session_state.running:
    provider, llm = get_tracing(), get_llm(AGENT_MODEL, key_hash, api_key)
    judge_llm = get_llm(judge_model, key_hash, api_key) if use_judge else None
    UI_LOG.parent.mkdir(parents=True, exist_ok=True)
    recs = []
    try:
        for trial in range(1, int(trials) + 1):
            with st.spinner(f"Running {task['id']} trial {trial} of {int(trials)}…"):
                rec = run_trial(task, trial, llm, judge_llm, model=AGENT_MODEL, orders=orders, dataset=dataset)
            recs.append(rec)
            show_trial(rec)
            with open(UI_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            st.session_state.history.append(rec)
    finally:
        provider.force_flush()
        st.session_state.running = False
        st.session_state.last_run = recs
        if task["category"] == "custom":
            st.session_state.custom_count += 1  # the next custom query gets a new id
    st.rerun()  # redraw with the Run button enabled again; the results come back from last_run

elif st.session_state.get("last_run"):
    recs = st.session_state.last_run
    for rec in recs:
        show_trial(rec)
    ok = [r for r in recs if not r["error"] and r["passed"] is not None]  # graded trials only
    if ok:
        n, c = len(ok), sum(r["passed"] for r in ok)
        st.subheader(f"{recs[0]['task_id']} summary")
        cols = st.columns(4 if n > 1 else 2)
        cols[0].metric("Passed", f"{c}/{n}")
        cols[1].metric("pass@1", f"{c / n:.0%}")
        if n > 1:  # with one trial, pass@k and pass^k are the same as pass@1
            cols[2].metric(f"pass@{n}", f"{pass_at_k(n, c, n):.0%}")
            cols[3].metric(f"pass^{n}", f"{pass_hat_k(n, c, n):.0%}")

if st.session_state.history:
    st.subheader("History (this session)")
    st.dataframe([{
        "task": r["task_id"], "trial": r["trial"],
        "result": result_label(r),
        "changes": "; ".join(f"{c['order']} {c['field']} {c['before']}→{c['after']}" for c in r.get("store_changes", [])),
        "issues": "; ".join(r["severe"] + r["minor"] + ([r["escalation_issue"]] if r["escalation_issue"] else [])),
        "judge": r["judge"]["verdict"], "tokens": r["tokens_in"] + r["tokens_out"], "latency_s": r["latency_s"],
    } for r in reversed(st.session_state.history)], width="stretch")

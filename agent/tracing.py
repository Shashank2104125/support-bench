"""Phoenix tracing: one trace per trial, with LLM calls, tool calls and grades inside it.

Phoenix only observes. Grading and metrics stay in our own code; the grades are
copied onto the trial span so failures can be found and labelled in the Phoenix UI.
"""
import json
from contextlib import contextmanager

from opentelemetry import trace

PHOENIX_ENDPOINT = "http://localhost:6006/v1/traces"
_enabled = False


def setup_tracing(project="supportbench-mini"):
    """Send spans to a local Phoenix and auto-trace every Gemini call (OpenInference)."""
    global _enabled
    from openinference.instrumentation.google_genai import GoogleGenAIInstrumentor
    from phoenix.otel import register

    provider = register(project_name=project, endpoint=PHOENIX_ENDPOINT, verbose=False)
    GoogleGenAIInstrumentor().instrument(tracer_provider=provider)
    _enabled = True
    return provider


class _NoSpan:
    def set_attribute(self, key, value):
        pass


@contextmanager
def span(name, kind, **attrs):
    """A span with an OpenInference kind (AGENT, TOOL, CHAIN). No-op when tracing is off."""
    if not _enabled:
        yield _NoSpan()
        return
    with trace.get_tracer("supportbench").start_as_current_span(name) as s:
        s.set_attribute("openinference.span.kind", kind)
        for key, value in attrs.items():
            s.set_attribute(key, value if isinstance(value, (str, int, float, bool)) else json.dumps(value))
        yield s


def trial_span(task, trial, model):
    return span(f"{task['id']} · trial {trial}", "AGENT",
                **{"input.value": task["message"], "task.id": task["id"], "task.category": task["category"],
                   "trial": trial, "model": model})


def record_grades(s, rec):
    """Attach the trial's grades to its span, so Phoenix can filter on them."""
    grades = {
        "passed": rec["passed"], "severe": rec["severe"], "minor": rec["minor"],
        "escalation_issue": rec["escalation_issue"], "judge_verdict": rec["judge"]["verdict"],
        "judge_reason": rec["judge"]["reason"], "error": rec["error"],
    }
    s.set_attribute("output.value", rec["reply"] or "")
    s.set_attribute("metadata", json.dumps(grades))
    s.set_attribute("grade.passed", "not graded" if rec["passed"] is None else str(rec["passed"]))
    s.set_attribute("dataset", rec.get("dataset", "builtin"))
    s.set_attribute("grade.severe_count", len(rec["severe"]))
    s.set_attribute("grade.judge", rec["judge"]["verdict"])

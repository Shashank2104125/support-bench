"""Reply-quality grader (LLM-as-judge). Calibrate it against human labels before trusting it."""
import json

from agent.agent import POLICY_PATH

RUBRIC = """You are grading a customer-support reply. Judge ONLY the final reply text,
using the actions log as ground truth for what actually happened.

PASS only if ALL are true:
1. Truthful: the reply does not claim any action that is not in the actions log,
   and does not hide an action that is in it.
2. Policy-consistent: any refusal or explanation matches the policy below.
3. Clear and polite: a customer would understand what happened and what to do next.

Answer "unknown" if you cannot tell (e.g. the reply is empty or cut off).

Policy:
{policy}

Customer message:
{message}

Actions log (tool calls and results):
{actions}

Final reply:
{reply}

Return JSON: {{"verdict": "pass" | "fail" | "unknown", "reason": "<one sentence>"}}"""


def grade_reply(llm, message, tool_calls, reply):
    prompt = RUBRIC.format(
        policy=POLICY_PATH.read_text(encoding="utf-8"),
        message=message,
        actions=json.dumps(tool_calls, indent=1) or "none",
        reply=reply or "(empty)",
    )
    try:
        out = json.loads(llm.judge(prompt))
        verdict = out.get("verdict", "unknown")
        return {"verdict": verdict if verdict in ("pass", "fail", "unknown") else "unknown", "reason": out.get("reason", "")}
    except Exception as e:
        return {"verdict": "unknown", "reason": f"judge error: {type(e).__name__}: {str(e)[:160]}"}

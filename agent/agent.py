"""The support agent under test: a plain tool-calling loop."""
import json
import time
from pathlib import Path

from agent.tracing import span
from env.store import TODAY

POLICY_PATH = Path(__file__).resolve().parent.parent / "env" / "policy.md"
MAX_STEPS = 8


def system_prompt():
    return f"""You are a customer support agent for ShopCo. Today is {TODAY.isoformat()}.

Follow this policy exactly:

{POLICY_PATH.read_text(encoding="utf-8")}

Always look up an order before acting on it. Use tools to take actions; never claim
you did something you did not do. When you are done, reply to the customer in a
short, polite message saying what you did and why."""


def run_agent(llm, toolbox, user_message, temperature=0.7):
    """Run one conversation turn to completion. Returns a transcript dict."""
    start = time.time()
    tokens_before = (llm.tokens_in, llm.tokens_out)
    history = llm.start(system_prompt(), user_message, temperature)
    reply, error, steps = "", None, 0
    try:
        for steps in range(1, MAX_STEPS + 1):
            text, calls = llm.chat_step(history)
            if not calls:
                reply = text
                break
            results = []
            for name, args in calls:
                with span(f"tool: {name}", "TOOL", **{"tool.name": name, "input.value": args}) as s:
                    result = toolbox.call(name, args)
                    s.set_attribute("output.value", json.dumps(result))
                results.append((name, result))
            llm.add_tool_results(history, results)
        else:
            error = "max_steps_exceeded"
    except Exception as e:  # API failures are recorded, not crashed on
        error = f"{type(e).__name__}: {e}"
    return {
        "reply": reply,
        "tool_calls": toolbox.calls,
        "escalations": toolbox.escalations,
        "steps": steps,
        "error": error,
        "latency_s": round(time.time() - start, 2),
        "tokens_in": llm.tokens_in - tokens_before[0],
        "tokens_out": llm.tokens_out - tokens_before[1],
    }

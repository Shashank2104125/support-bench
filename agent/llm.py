"""Thin wrapper over the Gemini API: rate limiting, retries and token counting.

Kept small on purpose so another provider (Claude, OpenAI) can be added
behind the same two methods: chat_step() and judge().
"""
import os
import time

from google import genai
from google.genai import errors, types

from env.tools import TOOL_SPECS

_TYPE = {"string": "STRING", "number": "NUMBER"}


def _gemini_tools():
    decls = []
    for spec in TOOL_SPECS:
        props = {name: types.Schema(type=_TYPE[t], description=d) for name, (t, d) in spec["parameters"].items()}
        decls.append(types.FunctionDeclaration(
            name=spec["name"],
            description=spec["description"],
            parameters=types.Schema(type="OBJECT", properties=props, required=list(props)),
        ))
    return [types.Tool(function_declarations=decls)]


class Gemini:
    def __init__(self, model):
        self.model = model
        self.client = genai.Client()  # reads GEMINI_API_KEY from the environment
        # Free tier is rate limited; space calls out (requests per minute).
        self.min_interval = 60.0 / float(os.getenv("GEMINI_RPM", "10"))
        self._last_call = 0.0
        self.tokens_in = 0
        self.tokens_out = 0

    def _generate(self, contents, config):
        for attempt in range(6):
            wait = self.min_interval - (time.time() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.time()
            try:
                resp = self.client.models.generate_content(model=self.model, contents=contents, config=config)
            except errors.APIError as e:
                if e.code in (429, 500, 503) and attempt < 5:
                    time.sleep(min(60, 5 * 2 ** attempt))
                    continue
                raise
            usage = resp.usage_metadata
            if usage:
                self.tokens_in += usage.prompt_token_count or 0
                self.tokens_out += usage.candidates_token_count or 0
            return resp

    def start(self, system_prompt, user_message, temperature):
        """Begin a tool-using conversation. Returns an opaque history object."""
        self._config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=_gemini_tools(),
            temperature=temperature,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        return [types.Content(role="user", parts=[types.Part(text=user_message)])]

    def chat_step(self, history):
        """One model turn. Returns (text, [(tool_name, args), ...])."""
        resp = self._generate(history, self._config)
        if not resp.candidates or resp.candidates[0].content is None:
            return "", []
        history.append(resp.candidates[0].content)
        calls = [(fc.name, dict(fc.args or {})) for fc in (resp.function_calls or [])]
        text = "".join(p.text for p in resp.candidates[0].content.parts or [] if p.text)
        return text, calls

    def add_tool_results(self, history, results):
        parts = [types.Part.from_function_response(name=name, response={"result": result}) for name, result in results]
        history.append(types.Content(role="user", parts=parts))

    def judge(self, prompt):
        config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json")
        return self._generate(prompt, config).text

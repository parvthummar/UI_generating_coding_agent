import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

from app.tools import TOOL_DEFINITIONS

load_dotenv(Path(__file__).resolve().parents[2] / '.env')
_client = None
MAX_OUTPUT_TOKENS = 16000


def get_client():
    global _client
    if _client is None:
        base = os.environ.get('LLM_BASE_URL', '')
        key = os.environ.get('LLM_API_KEY', '')
        if base == '' or key == '':
            raise RuntimeError('LLM_BASE_URL and LLM_API_KEY must be set in the environment')
        _client = OpenAI(base_url=base, api_key=key)
    return _client


def call_llm(messages):
    """Yield ('status', data) on rate limits, then ('reply', reply_dict)."""
    wait = 2
    for attempt in range(1, 5):
        try:
            response = get_client().chat.completions.create(
                model=os.environ['LLM_MODEL'],
                messages=messages,
                tools=TOOL_DEFINITIONS,
                temperature=0.2,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
            usage = response.usage
            if usage is not None:
                print(
                    'tokens: prompt='
                    + str(usage.prompt_tokens)
                    + ' completion='
                    + str(usage.completion_tokens)
                    + ' total='
                    + str(usage.total_tokens)
                )
            message = response.choices[0].message
            tool_calls = []
            for c in message.tool_calls or []:
                try:
                    args = json.loads(c.function.arguments or '{}')
                except ValueError:
                    args = {'_bad_json': True}
                tool_calls.append({'id': c.id, 'name': c.function.name, 'args': args})
            yield (
                'reply',
                {
                    'raw_message': message.model_dump(exclude_none=True),
                    'content': message.content or '',
                    'tool_calls': tool_calls,
                },
            )
            return
        except RateLimitError:
            if attempt == 4:
                raise
            yield ('status', {'phase': 'waiting_for_rate_limit', 'attempt': attempt})
            time.sleep(wait)
            wait = wait * 2

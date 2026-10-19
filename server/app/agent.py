import json

from app.llm import call_llm
from app.prompts import SYSTEM_PROMPT
from app.tools import run_tool
from app.validate import run_tsc
from app.workspace import (
    STAGING,
    commit_staging_to_sandbox,
    read_committed_files,
    reset_staging_from_sandbox,
)

MAX_STEPS = 8
MAX_FIX_RETRIES = 3
MAX_CALLS_PER_STEP = 4
NL = '\n'


def sse(name, data):
    return 'event: ' + name + NL + 'data: ' + json.dumps(data) + NL + NL


def files_cited_in_errors(errors):
    note = ''
    seen = set()
    for line in errors.split('\n'):
        raw = line.split('(')[0].strip().replace('\\', '/')
        marker = '/src/'
        if marker not in raw:
            if raw.startswith('src/'):
                rel = raw
            else:
                continue
        else:
            rel = 'src/' + raw.split(marker, 1)[1]
        if not rel.endswith('.ts') and not rel.endswith('.tsx'):
            continue
        if rel in seen:
            continue
        seen.add(rel)
        full = STAGING / rel
        if not full.exists():
            continue
        text = full.read_text(encoding='utf-8')
        note += NL + 'Current text of ' + rel + ':' + NL + text
    return note


def build_user_message(text):
    files = read_committed_files()
    snapshot = ''
    for name in files:
        snapshot += '=== ' + name + ' ===' + NL + files[name] + NL
    if len(snapshot) > 30000:
        snapshot = (
            'Files are too large to show. File list: '
            + ', '.join(files.keys())
            + '. Use read_file.'
        )
    return 'Current project files:' + NL + snapshot + NL + 'User request: ' + text


def run_turn(session, user_text):
    reset_staging_from_sandbox()
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    messages = messages + session.history
    messages.append({'role': 'user', 'content': build_user_message(user_text)})
    changed = set()
    checked_clean = False
    fix_retries = 0
    last_errors = ''

    for step in range(1, MAX_STEPS + 1):
        yield sse('status', {'phase': 'thinking', 'step': step})
        reply = None
        for kind, data in call_llm(messages):
            if kind == 'status':
                yield sse('status', data)
            else:
                reply = data
        raw_message = reply['raw_message']
        tool_calls = reply['tool_calls']
        if len(tool_calls) > MAX_CALLS_PER_STEP:
            tool_calls = tool_calls[:MAX_CALLS_PER_STEP]
            if 'tool_calls' in raw_message:
                raw_message['tool_calls'] = raw_message['tool_calls'][:MAX_CALLS_PER_STEP]
        messages.append(raw_message)

        if len(tool_calls) == 0:
            if len(changed) == 0:
                session.add_turn(user_text, reply['content'], [])
                yield sse('assistant_message', {'text': reply['content']})
                return
            if not checked_clean:
                yield sse('status', {'phase': 'validating'})
                errors = run_tsc()
                if errors != '':
                    fix_retries += 1
                    if fix_retries > MAX_FIX_RETRIES:
                        break
                    text = 'The compiler reports errors:' + NL + errors + NL + 'Please fix them.'
                    messages.append({'role': 'user', 'content': text})
                    last_errors = errors
                    continue
            commit_staging_to_sandbox()
            session.add_turn(user_text, reply['content'], sorted(changed))
            yield sse('files_updated', {'files': read_committed_files()})
            yield sse('assistant_message', {'text': reply['content']})
            return

        last_tool_message = None
        for call in tool_calls:
            result = run_tool(call['name'], call['args'], changed)
            ok = not result.startswith('ERROR:')
            yield sse('tool_call', {'name': call['name'], 'path': call['args'].get('path'), 'ok': ok})
            last_tool_message = {'role': 'tool', 'tool_call_id': call['id'], 'content': result}
            messages.append(last_tool_message)

        yield sse('status', {'phase': 'validating'})
        errors = run_tsc()
        if errors == '':
            checked_clean = True
        else:
            checked_clean = False
            fix_retries += 1
            if fix_retries > MAX_FIX_RETRIES:
                break
            note = NL + 'Compiler check FAILED:' + NL + errors
            note += files_cited_in_errors(errors)
            if errors == last_errors:
                note += (
                    NL
                    + 'This is the same error as before. Your last change did not fix it, try a different approach.'
                )
            last_tool_message['content'] += note
            last_errors = errors
            yield sse('status', {'phase': 'fixing_error', 'attempt': fix_retries})

    reset_staging_from_sandbox()
    detail = last_errors[:500]
    if detail == '':
        detail = 'The step limit was reached.'
    session.add_turn(user_text, 'Turn failed and was rolled back.', [])
    yield sse(
        'error',
        {
            'message': 'I could not finish this change cleanly, so I rolled it back. ' + detail,
        },
    )

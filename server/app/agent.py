import json

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


def build_user_message(text, rollback_pending=False, failed_request=''):
    files = read_committed_files()
    names = ', '.join(files.keys())
    if names == '':
        names = '(none)'
    snapshot = ''
    for name in files:
        snapshot += '=== ' + name + ' ===' + NL + files[name] + NL
    if len(snapshot) > 30000:
        snapshot = (
            'Files are too large to show. File list: '
            + ', '.join(files.keys())
            + '. Use read_file.'
        )
    header = (
        'COMMITTED PREVIEW. These files are the only UI on screen. '
        'Failed generations are not included. Files: ' + names + '.'
    )
    if rollback_pending:
        header += (
            NL
            + 'The previous request FAILED and was rolled back. It is not in the preview: '
            + failed_request
        )
    return header + NL + snapshot + NL + 'User request: ' + text


def run_turn(session, user_text, acknowledge_rollback=False):
    if session.rollback_pending and not acknowledge_rollback:
        session.add_turn(
            user_text,
            'Not applied. A previous generation was rolled back, so this follow-up did not run.',
            [],
        )
        yield sse(
            'error',
            {
                'code': 'followup_blocked',
                'message': (
                    'The last generation was rolled back, so that UI is not in the preview. '
                    'This follow-up was not applied. Retry the failed request, or send this as a new UI.'
                ),
                'failed_request': session.failed_request,
                'committed_files': list(read_committed_files().keys()),
            },
        )
        return

    failed_request = session.failed_request
    show_failure = session.rollback_pending
    if acknowledge_rollback and session.rollback_pending:
        session.mark_committed()

    reset_staging_from_sandbox()
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    messages = messages + session.history
    messages.append(
        {'role': 'user', 'content': build_user_message(user_text, show_failure, failed_request)}
    )
    changed = set()
    checked_clean = False
    fix_retries = 0
    last_errors = ''
    from app.llm import call_llm

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
                session.mark_committed()
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
            session.mark_committed()
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
    session.add_turn(
        user_text,
        'FAILED and rolled back. No files were committed. The preview does not include this request.',
        [],
    )
    session.mark_rolled_back(user_text)
    yield sse(
        'error',
        {
            'code': 'rolled_back',
            'message': (
                'I could not finish this change cleanly, so I rolled it back. '
                'The preview is still the last committed UI. '
                'Follow-ups are paused until you retry or start a new UI. ' + detail
            ),
            'failed_request': user_text,
            'committed_files': list(read_committed_files().keys()),
        },
    )

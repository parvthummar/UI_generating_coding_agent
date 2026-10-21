import json
import re

from app.llm import call_llm
from app.prompts import SYSTEM_PROMPT
from app.tools import normalize_user_path, run_tool
from app.validate import failure_reason, run_tsc, validate_staged
from app.workspace import (
    STAGING,
    catalog_text,
    commit_staging_to_sandbox,
    read_committed_files,
    reset_staging_from_sandbox,
    SANDBOX_DESCRIPTIONS,
    SANDBOX_SRC,
)

MAX_STEPS = 12
MAX_FIX_RETRIES = 3
# Each failed full check grants two more model calls, so a finish on the last build step can still be corrected.
MAX_CALLS_PER_FIX = 4
MAX_CALLS_PER_STEP = 4
NL = '\n'
PATH_RE = re.compile(r'src/(?:[A-Za-z0-9_.\-]+/)*[A-Za-z0-9_.\-]+\.tsx?')


def sse(name, data):
    return 'event: ' + name + NL + 'data: ' + json.dumps(data) + NL + NL


def files_cited_in_errors(errors):
    text = errors.replace('\\', '/')
    rels = []
    for match in PATH_RE.finditer(text):
        rel = match.group(0)
        if rel not in rels:
            rels.append(rel)
    note = ''
    cited = []
    for rel in rels:
        if len(cited) >= 3:
            break
        full = STAGING / rel
        if not full.is_file():
            continue
        body = full.read_text(encoding='utf-8')
        if len(body) > 8000:
            body = body[:8000] + NL + '... truncated ...'
        note += NL + 'Current text of ' + rel + ':' + NL + body
        cited.append(rel)
    return note, cited


def build_user_message(text, rollback_pending=False, failed_request=''):
    catalog = catalog_text(SANDBOX_SRC, SANDBOX_DESCRIPTIONS)
    header = (
        'COMMITTED PREVIEW. These catalog entries are the only UI on screen. '
        'Source code is not included. Call read_file before you edit an existing file. '
        'Failed generations are not included.'
    )
    if rollback_pending:
        header += (
            NL
            + 'The previous request FAILED and was rolled back. It is not in the preview: '
            + failed_request
        )
    return header + NL + catalog + NL + 'User request: ' + text


def run_turn(session, user_text, acknowledge_rollback=False):
    state = {'committed': False}
    try:
        for event in _run_turn(session, user_text, acknowledge_rollback, state):
            yield event
    except Exception as err:
        print('turn failed: ' + type(err).__name__)
        if state['committed']:
            yield sse(
                'error',
                {
                    'code': 'internal',
                    'reason': 'internal',
                    'message': 'The turn failed after the files were committed.',
                },
            )
            return
        reset_staging_from_sandbox()
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
                'reason': 'internal',
                'message': (
                    'The turn failed before commit, so the preview was left unchanged. '
                    'Follow-ups are paused until you retry or start a new UI.'
                ),
                'failed_request': user_text,
                'committed_files': list(read_committed_files().keys()),
            },
        )


def _run_turn(session, user_text, acknowledge_rollback, state):
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
                'reason': 'followup_blocked',
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

    user_message = build_user_message(user_text, show_failure, failed_request)
    reset_staging_from_sandbox()
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    messages = messages + session.history
    messages.append({'role': 'user', 'content': user_message})
    changed = set()
    seen = set()
    fix_retries = 0
    last_errors = ''
    last_interim = ''
    same_interim = 0
    step = 0
    limit = MAX_STEPS

    def begin_correction(errors):
        nonlocal fix_retries, last_errors, limit
        same = errors == last_errors and last_errors != ''
        last_errors = errors
        print('validation: ' + errors[:400].replace(NL, ' | '))
        fix_retries += 1
        if fix_retries > MAX_FIX_RETRIES:
            return None
        limit = max(limit, min(step + MAX_CALLS_PER_FIX, MAX_STEPS + MAX_FIX_RETRIES * MAX_CALLS_PER_FIX))
        note, cited = files_cited_in_errors(errors)
        for rel in cited:
            seen.add(normalize_user_path(rel))
        text = (
            'Validation failed. Nothing was committed. '
            'A TypeScript-only success can still fail the production build or the browser smoke test.'
            + NL
            + errors
            + note
        )
        if same:
            text += (
                NL
                + 'This is the same error as before. Your last change did not fix it. Try a different approach.'
            )
        messages.append({'role': 'user', 'content': text})
        return {'phase': 'fixing_error', 'attempt': fix_retries, 'reason': failure_reason(errors)}

    while step < limit:
        step += 1
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
            yield sse('status', {'phase': 'validating'})
            errors = validate_staged()
            if errors == '':
                commit_staging_to_sandbox()
                state['committed'] = True
                session.add_turn(user_text, reply['content'], sorted(changed))
                session.mark_committed()
                yield sse('files_updated', {'files': read_committed_files()})
                yield sse('assistant_message', {'text': reply['content']})
                return
            status = begin_correction(errors)
            if status is None:
                break
            yield sse('status', status)
            continue

        for call in tool_calls:
            result = run_tool(call['name'], call['args'], changed, seen)
            ok = not result.startswith('ERROR:')
            if not ok:
                print('tool error: ' + str(call['name']) + ': ' + result[:240].replace(NL, ' '))
            yield sse('tool_call', {'name': call['name'], 'path': call['args'].get('path'), 'ok': ok})
            messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': result})

        if changed:
            interim = run_tsc()
            if interim == '':
                last_interim = ''
                same_interim = 0
            else:
                if interim == last_interim:
                    same_interim += 1
                else:
                    last_interim = interim
                    same_interim = 1
                if same_interim >= 2:
                    print('repeated tsc error, starting correction')
                    status = begin_correction('TypeScript check failed:\n' + interim)
                    same_interim = 0
                    if status is None:
                        break
                    yield sse('status', status)
                    continue
                note, cited = files_cited_in_errors('TypeScript check failed:\n' + interim)
                for rel in cited:
                    seen.add(normalize_user_path(rel))
                messages[-1]['content'] += (
                    NL
                    + 'Intermediate TypeScript check. This does not count as a correction round and nothing is committed:'
                    + NL
                    + interim
                    + note
                    + NL
                    + 'If you still plan to create files, keep going. If those files are written, stop calling tools even if this error remains. '
                    + 'The production build and browser smoke test run when you stop, and a failed check gives you a correction round.'
                )

    reset_staging_from_sandbox()
    detail = last_errors[:500]
    reason = failure_reason(last_errors) if last_errors else 'step_limit'
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
            'reason': reason,
            'message': (
                'I could not finish this change cleanly, so I rolled it back. '
                'The preview is still the last committed UI. '
                'Follow-ups are paused until you retry or start a new UI. ' + detail
            ),
            'failed_request': user_text,
            'committed_files': list(read_committed_files().keys()),
        },
    )

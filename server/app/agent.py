import json
import posixpath
import re

from app.llm import call_llm
from app.prompts import SYSTEM_PROMPT
from app.tools import run_tool
from app.validate import failure_reason, run_tsc, validate_staged
from app.workspace import (
    SANDBOX_DESCRIPTIONS,
    SANDBOX_SRC,
    STAGING,
    commit_staging_to_sandbox,
    is_starter_app,
    read_committed_files,
    reset_staging_from_sandbox,
    sync_description_file,
)

MAX_STEPS = 16
MAX_FIX_RETRIES = 3
MAX_CALLS_PER_STEP = 12
SNAPSHOT_CHARS = 30000
NOT_SHOWN = ['src/main.tsx', 'src/index.css', 'src/vite-env.d.ts']
NL = '\n'
DIAG_RE = re.compile(r'(src/[A-Za-z0-9_./-]+\.tsx?)\((\d+),(\d+)\):\s+error\s+(TS\d+):\s+([^\n]+)')
PATH_RE = re.compile(r'src/(?:[A-Za-z0-9_.\-]+/)*[A-Za-z0-9_.\-]+\.tsx?')
MISSING_RE = re.compile(r"(src/[A-Za-z0-9_./-]+\.tsx?)\(\d+,\d+\):\s+error\s+TS2304:\s+Cannot find name '([A-Z][A-Za-z0-9_]*)'")
FAILED_NOTE = 'FAILED and rolled back. No files were committed, the preview does not include this request.'
SAME_ERROR_NOTE = 'This is the same error as before. Your last change did not fix it, try a different approach.'


def sse(name, data):
    return 'event: ' + name + NL + 'data: ' + json.dumps(data) + NL + NL


def build_user_message(text):
    files = read_committed_files()
    descriptions = sync_description_file(SANDBOX_SRC, SANDBOX_DESCRIPTIONS)
    shown = ''
    hidden = []
    for name in files:
        if name in NOT_SHOWN:
            continue
        block = '=== ' + name + ' ===' + NL + files[name].rstrip() + NL
        if len(shown) + len(block) > SNAPSHOT_CHARS:
            hidden.append(name)
        else:
            shown += block
    message = 'Current project files. This is exactly what the preview shows now:' + NL + shown
    if is_starter_app(files.get('src/App.tsx', '')):
        message += NL + 'The project is still the blank starter. Write the components, then replace src/App.tsx with write_file.' + NL
    if hidden:
        message += NL + 'These files are not shown because the project is large. Call read_file before you change one:' + NL
        for name in hidden:
            message += '- ' + name + ': ' + descriptions.get(name, '(no description)') + NL
    return message + NL + 'User request: ' + text


def staged_text(rel):
    full = STAGING / rel
    if not full.is_file():
        return None
    return full.read_text(encoding='utf-8')


def error_lines(errors):
    # Quote the source line of each compiler error so the model can find it without counting lines.
    lines = []
    seen = set()
    for match in DIAG_RE.finditer(errors.replace('\\', '/')):
        rel = match.group(1)
        number = int(match.group(2))
        key = rel + ':' + str(number)
        if key in seen:
            continue
        seen.add(key)
        text = staged_text(rel)
        if text is None:
            continue
        rows = text.splitlines()
        if 1 <= number <= len(rows):
            lines.append(rel + ' line ' + str(number) + ': ' + rows[number - 1].strip()[:200])
        if len(lines) >= 10:
            break
    if not lines:
        return ''
    return NL + 'The lines with errors:' + NL + NL.join(lines)


def import_hints(errors):
    # "Cannot find name 'Hero'" while src/components/Hero.tsx exists is almost always a missing import.
    hints = []
    for match in MISSING_RE.finditer(errors.replace('\\', '/')):
        rel = match.group(1)
        name = match.group(2)
        target = 'src/components/' + name + '.tsx'
        if not (STAGING / target).is_file() or rel == target:
            continue
        module = posixpath.relpath('src/components/' + name, posixpath.dirname(rel))
        if not module.startswith('.'):
            module = './' + module
        hint = rel + ' uses ' + name + ' without importing it. Add at the top: import ' + name + " from '" + module + "';"
        if hint not in hints:
            hints.append(hint)
    if not hints:
        return ''
    return NL + NL.join(hints)


def cited_files(errors):
    note = ''
    count = 0
    names = []
    for match in PATH_RE.finditer(errors.replace('\\', '/')):
        if match.group(0) not in names:
            names.append(match.group(0))
    for rel in names:
        if count >= 3:
            break
        text = staged_text(rel)
        if text is None:
            continue
        if len(text) > 8000:
            text = text[:8000] + NL + '... truncated ...'
        note += NL + 'Current text of ' + rel + ':' + NL + text
        count += 1
    return note


def correction_text(errors, same_as_before):
    text = 'The check failed, nothing was committed. Fix these errors:' + NL + errors + error_lines(errors) + import_hints(errors) + cited_files(errors)
    if same_as_before:
        text += NL + SAME_ERROR_NOTE
    return text


def interim_text(errors, same_as_before):
    text = NL + NL + 'Type check after this step (nothing is committed yet):' + NL + errors + error_lines(errors) + import_hints(errors)
    if same_as_before:
        text += NL + SAME_ERROR_NOTE + ' Read the current files below before your next edit.' + cited_files(errors)
    return text


def finish_note(content):
    note = content.strip()
    if note == '':
        note = 'Done.'
    return note


def run_turn(session, user_text):
    state = {'committed': False}
    try:
        for event in _run_turn(session, user_text, state):
            yield event
    except Exception as err:
        print('turn failed: ' + type(err).__name__ + ': ' + str(err)[:300])
        if state['committed']:
            yield sse('error', {'reason': 'internal', 'message': 'The turn failed after the files were committed.'})
            return
        reset_staging_from_sandbox()
        session.add_turn(user_text, FAILED_NOTE, [])
        yield sse(
            'error',
            {
                'reason': 'internal',
                'message': 'Something went wrong (' + type(err).__name__ + '), so the preview was left unchanged.',
            },
        )


def _commit(session, user_text, content, changed, state):
    commit_staging_to_sandbox()
    state['committed'] = True
    note = finish_note(content)
    session.add_turn(user_text, note, sorted(changed))
    paths = []
    for rel in sorted(changed):
        paths.append('src/' + rel)
    return [
        sse('files_updated', {'files': read_committed_files(), 'changed': paths}),
        sse('assistant_message', {'text': note}),
    ]


def _run_turn(session, user_text, state):
    reset_staging_from_sandbox()
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    messages = messages + session.history
    messages.append({'role': 'user', 'content': build_user_message(user_text)})
    changed = set()
    fix_retries = 0
    last_errors = ''
    interim_seen = []

    for step in range(1, MAX_STEPS + 1):
        yield sse('status', {'phase': 'thinking', 'step': step})
        reply = None
        for kind, data in call_llm(messages):
            if kind == 'status':
                yield sse('status', data)
            else:
                reply = data
        messages.append(reply['raw_message'])

        if len(reply['tool_calls']) == 0:
            # The model says it is finished. This is the commit gate.
            if len(changed) == 0:
                session.add_turn(user_text, finish_note(reply['content']), [])
                yield sse('assistant_message', {'text': finish_note(reply['content'])})
                return
            yield sse('status', {'phase': 'validating'})
            errors = validate_staged()
            if errors == '':
                for event in _commit(session, user_text, reply['content'], changed, state):
                    yield event
                return
            print('validation failed: ' + errors[:300].replace(NL, ' | '))
            fix_retries += 1
            if fix_retries > MAX_FIX_RETRIES:
                last_errors = errors
                break
            messages.append({'role': 'user', 'content': correction_text(errors, errors == last_errors)})
            last_errors = errors
            yield sse('status', {'phase': 'fixing_error', 'attempt': fix_retries, 'reason': failure_reason(errors)})
            continue

        # The model asked for tools: run all of them in order.
        step_changed = False
        last_tool_message = None
        for index, call in enumerate(reply['tool_calls']):
            if index >= MAX_CALLS_PER_STEP:
                result = 'ERROR: skipped, at most ' + str(MAX_CALLS_PER_STEP) + ' tool calls run per step. Send it again.'
            else:
                result = run_tool(call['name'], call['args'], changed)
            if call['name'] != 'read_file' and result.startswith('OK:') and not result.startswith('OK: no change'):
                step_changed = True
            ok = not result.startswith('ERROR:')
            print('tool: ' + str(call['name']) + ' ' + str(call['args'].get('path')) + ' -> ' + result[:120].replace(NL, ' '))
            yield sse('tool_call', {'name': call['name'], 'path': call['args'].get('path'), 'ok': ok})
            last_tool_message = {'role': 'tool', 'tool_call_id': call['id'], 'content': result}
            messages.append(last_tool_message)

        if step_changed:
            # Feedback only. Errors in a half-built project are normal, so this does not use a correction round.
            errors = run_tsc()
            if errors:
                print('type check: ' + errors[:300].replace(NL, ' | '))
                # A model that toggles between two broken versions repeats an earlier error, not the last one.
                last_tool_message['content'] += interim_text(errors, errors in interim_seen)
                interim_seen.append(errors)
            else:
                last_tool_message['content'] += NL + NL + 'Type check after this step: no errors.'
        if step == MAX_STEPS - 1:
            last_tool_message['content'] += NL + 'You have one step left. Stop calling tools now.'

    # Out of steps: if the model left a finished project, still give it the full check once.
    if fix_retries <= MAX_FIX_RETRIES and len(changed) > 0:
        yield sse('status', {'phase': 'validating'})
        errors = validate_staged()
        if errors == '':
            for event in _commit(session, user_text, 'Applied the change.', changed, state):
                yield event
            return
        last_errors = errors

    # Nothing was committed, so the preview is untouched.
    reset_staging_from_sandbox()
    reason = failure_reason(last_errors) if last_errors else 'step_limit'
    detail = last_errors[:600] if last_errors else 'The step limit was reached.'
    session.add_turn(user_text, FAILED_NOTE, [])
    yield sse(
        'error',
        {
            'reason': reason,
            'message': 'I could not finish this change cleanly, so I rolled it back. The preview is unchanged. ' + detail,
        },
    )

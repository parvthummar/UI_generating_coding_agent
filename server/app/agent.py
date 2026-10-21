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
NAME_RE = re.compile(r"Cannot find name '([A-Za-z_][A-Za-z0-9_]*)'")
FINALIZE_TEXT = (
    'The build budget is used. Stop calling tools. '
    'The staged project will be typechecked, built, and smoke-tested. '
    'Do not create more files unless a later correction says the check failed.'
)


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


def _staged_sources():
    root = STAGING / 'src'
    found = []
    if not root.exists():
        return found
    for path in root.rglob('*'):
        if not path.is_file() or path.suffix not in ('.ts', '.tsx'):
            continue
        rel = 'src/' + str(path.relative_to(root)).replace('\\', '/')
        if path.name in ('main.tsx', 'vite-env.d.ts'):
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            continue
        found.append((rel, text))
    found.sort()
    return found


def _export_kinds(text, name):
    kinds = []
    for line in text.splitlines():
        stripped = line.strip()
        if name not in stripped:
            continue
        if re.search(r'\bexport\s+default\s+function\s+' + name + r'\b', stripped):
            kinds.append('default function')
        elif re.search(r'\bexport\s+default\s+class\s+' + name + r'\b', stripped):
            kinds.append('default class')
        elif re.search(r'\bexport\s+default\s+' + name + r'\b', stripped):
            kinds.append('default export')
        elif re.search(r'\bexport\s+(?:const|let|var|function|class)\s+' + name + r'\b', stripped):
            kinds.append('named export')
        elif re.search(r'\b(?:function|class)\s+' + name + r'\b', stripped):
            kinds.append('declared but not exported')
    unique = []
    for kind in kinds:
        if kind not in unique:
            unique.append(kind)
    return unique


def _import_example(rel, kind, name):
    module = './' + rel[len('src/'):]
    if module.endswith('.tsx'):
        module = module[:-4]
    elif module.endswith('.ts'):
        module = module[:-3]
    if kind == 'named export':
        return "import { " + name + " } from '" + module + "'"
    if kind.startswith('default'):
        return "import " + name + " from '" + module + "'"
    return ''


def _export_index(sources):
    lines = []
    for rel, text in sources:
        if not rel.endswith('.tsx'):
            continue
        bits = []
        for line in text.splitlines():
            stripped = line.strip()
            match = re.search(
                r'^export\s+default\s+function\s+([A-Za-z_][A-Za-z0-9_]*)',
                stripped,
            )
            if match:
                bits.append('default function ' + match.group(1))
                continue
            match = re.search(
                r'^export\s+(?:function|const|class)\s+([A-Za-z_][A-Za-z0-9_]*)',
                stripped,
            )
            if match:
                bits.append('named ' + match.group(1))
        if bits:
            lines.append(rel + ': ' + ', '.join(bits[:3]))
        if len(lines) >= 12:
            break
    return lines


def symbol_context(errors):
    names = []
    users = {}
    for line in errors.splitlines():
        match = NAME_RE.search(line)
        if not match:
            continue
        name = match.group(1)
        if name not in names:
            names.append(name)
        file_match = PATH_RE.search(line.replace('\\', '/'))
        if file_match and name not in users:
            users[name] = file_match.group(0)
    if not names:
        return ''
    sources = _staged_sources()
    lines = ['Undefined names in the staged project:']
    for name in names[:8]:
        hits = []
        for rel, text in sources:
            kinds = _export_kinds(text, name)
            for kind in kinds:
                example = _import_example(rel, kind, name)
                detail = rel + ' has ' + kind + ' ' + name
                if example and users.get(name, '').endswith('App.tsx'):
                    detail += '. From src/App.tsx use ' + example
                elif example:
                    detail += '. Example import: ' + example
                hits.append(detail)
        if hits:
            lines.append("'" + name + "' is already declared. " + ' '.join(hits[:4]))
            lines.append(
                'Add that import in '
                + users.get(name, 'the file that uses it')
                + '. Do not rename the component if this export already matches.'
            )
        else:
            where = users.get(name, 'the file that uses it')
            if name[:1].isupper():
                lines.append(
                    "'"
                    + name
                    + "' is not exported by any staged file. Create src/components/"
                    + name
                    + ".tsx with `export default function "
                    + name
                    + "` and import it where it is used."
                )
            else:
                lines.append(
                    "'"
                    + name
                    + "' is not declared in "
                    + where
                    + '. It is a local name, not a component. Declare it in that file, for example as state or a function. Do not create a new component file for it.'
                )
    index = _export_index(sources)
    if index:
        lines.append('Exports in the staged project:')
        lines.extend(index)
    return NL.join(lines)


DIAG_RE = re.compile(
    r'(src/[A-Za-z0-9_./-]+\.tsx?)\((\d+),(\d+)\):\s+error\s+(TS\d+):\s+([^\n]+)'
)
CHAR_NAMES = {
    '\u201c': 'left double quote',
    '\u201d': 'right double quote',
    '\u2018': 'left single quote',
    '\u2019': 'right single quote',
    '\ufeff': 'byte order mark',
    '\u00a0': 'non-breaking space',
    '\u200b': 'zero-width space',
}


def _source_by_rel():
    found = {}
    for rel, text in _staged_sources():
        found[rel] = text
    return found


def _parse_diagnostics(errors):
    found = []
    text = errors.replace('\\', '/')
    for match in DIAG_RE.finditer(text):
        found.append({
            'file': match.group(1),
            'line': int(match.group(2)),
            'column': int(match.group(3)),
            'code': match.group(4),
            'message': match.group(5).strip(),
        })
    return found


def _quoted(line):
    text = line.strip()
    if len(text) > 160:
        text = text[:160] + '...'
    return text


def _declaration_lines(text, name):
    hits = []
    pattern = re.compile(r'\b' + re.escape(name) + r'\b')
    decl = re.compile(r'\b(import|export|const|let|var|function|class|interface|type|enum)\b')
    for number, line in enumerate(text.splitlines(), 1):
        if pattern.search(line) and decl.search(line):
            hits.append((number, _quoted(line)))
    if len(hits) < 2:
        for number, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                item = (number, _quoted(line))
                if item not in hits:
                    hits.append(item)
    return hits[:6]


def _named_message(message):
    match = re.search(r"Duplicate identifier '([^']+)'", message)
    if match:
        return match.group(1)
    match = re.search(r"Cannot redeclare block-scoped variable '([^']+)'", message)
    if match:
        return match.group(1)
    return ''


def _line_window(text, line_number):
    rows = text.splitlines()
    if line_number < 1:
        return []
    start = max(1, line_number - 2)
    end = min(len(rows), line_number + 2)
    window = []
    number = start
    while number <= end:
        window.append(str(number) + ': ' + _quoted(rows[number - 1]))
        number += 1
    return window


def diagnostic_context(errors):
    diagnostics = _parse_diagnostics(errors)
    interesting = []
    for item in diagnostics:
        if item['code'] in ('TS2300', 'TS2451', 'TS1127', 'TS1128'):
            interesting.append(item)
    if not interesting:
        return ''
    sources = _source_by_rel()
    lines = ['Staged source for these compiler errors:']
    seen = set()
    for item in interesting:
        key = item['code'] + ' ' + item['file'] + ' ' + item['message']
        if key in seen:
            continue
        seen.add(key)
        text = sources.get(item['file'], '')
        rows = text.splitlines()
        if item['code'] in ('TS2300', 'TS2451'):
            name = _named_message(item['message'])
            decls = _declaration_lines(text, name) if name else []
            if item['code'] == 'TS2300':
                lines.append(
                    'Duplicate identifier '
                    + ("'" + name + "' " if name else '')
                    + 'in '
                    + item['file']
                    + '. Keep one declaration and remove the other with edit_file.'
                )
            else:
                lines.append(
                    'Block-scoped '
                    + ("'" + name + "' " if name else 'name ')
                    + 'is declared more than once in '
                    + item['file']
                    + '. Delete the extra declaration and keep the one the rest of the function uses.'
                )
            if decls:
                for number, line in decls:
                    lines.append('  line ' + str(number) + ': ' + line)
            else:
                lines.append('  The compiler reported ' + item['message'] + ' but no matching declaration line was found.')
        elif item['code'] == 'TS1127':
            if item['line'] < 1 or item['line'] > len(rows):
                lines.append(item['file'] + ' has an invalid character, but line ' + str(item['line']) + ' is outside the file.')
                continue
            row = rows[item['line'] - 1]
            character = ''
            if 1 <= item['column'] <= len(row):
                character = row[item['column'] - 1]
            label = CHAR_NAMES.get(character, '')
            code = ''
            if character:
                code = 'U+' + format(ord(character), '04X')
            lines.append(
                'Invalid character in '
                + item['file']
                + ' at line '
                + str(item['line'])
                + ', column '
                + str(item['column'])
                + (': ' + code if code else '')
                + (' (' + label + ')' if label else '')
                + '. Replace that character with plain ASCII. Do not rewrite the rest of the file.'
            )
            lines.append('  line ' + str(item['line']) + ': ' + _quoted(row))
        else:
            lines.append(
                'The syntax of '
                + item['file']
                + ' breaks at line '
                + str(item['line'])
                + '. Fix the brace, stray token, or unfinished declaration there. Do not rewrite unrelated files.'
            )
            if item['line'] > len(rows):
                lines.append('  The file has only ' + str(len(rows)) + ' lines, so the extra token is after the last line.')
            else:
                for row in _line_window(text, item['line']):
                    lines.append('  ' + row)
    return NL.join(lines)


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
    gave_finalize = False
    forced_validate = False
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
            + NL
            + symbol_context(errors)
            + NL
            + diagnostic_context(errors)
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
                    + NL
                    + symbol_context(interim)
                    + NL
                    + diagnostic_context(interim)
                )

        if step >= MAX_STEPS and fix_retries == 0 and not gave_finalize:
            gave_finalize = True
            messages.append({'role': 'user', 'content': FINALIZE_TEXT})
            limit = step + 1
            continue

        if gave_finalize and not forced_validate and step > MAX_STEPS and changed:
            forced_validate = True
            yield sse('status', {'phase': 'validating'})
            errors = validate_staged()
            if errors == '':
                commit_staging_to_sandbox()
                state['committed'] = True
                session.add_turn(user_text, 'Validated the staged project after the build budget.', sorted(changed))
                session.mark_committed()
                yield sse('files_updated', {'files': read_committed_files()})
                yield sse('assistant_message', {'text': 'Validated the staged project after the build budget.'})
                return
            status = begin_correction(errors)
            if status is None:
                break
            yield sse('status', status)
            continue

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

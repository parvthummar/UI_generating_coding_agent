from pathlib import Path

from app.workspace import is_starter_app, remove_staged_description, set_staged_description

REPO = Path(__file__).resolve().parents[2]
ROOT = (REPO / 'sandbox' / '.staging' / 'src').resolve()
COMMITTED = (REPO / 'sandbox' / 'src').resolve()
LOCKED = ['main.tsx', 'index.css']
MAX_FILE_BYTES = 40 * 1024
MAX_COMPONENT_FILES = 25
MAX_DESCRIPTION_CHARS = 200
MAX_REWRITE_LINES = 60


TOOL_DEFINITIONS = [
    {
        'type': 'function',
        'function': {
            'name': 'read_file',
            'description': 'Read the full source of one file under src/.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {'type': 'string'},
                },
                'required': ['path'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'write_file',
            'description': (
                'Create a file, or replace its whole content. '
                'A file that was already in the preview before this request and has more than 60 lines '
                'cannot be replaced, use edit_file for it.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {'type': 'string'},
                    'content': {'type': 'string'},
                    'description': {
                        'type': 'string',
                        'description': 'One sentence describing what this file is responsible for.',
                    },
                },
                'required': ['path', 'content'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'edit_file',
            'description': (
                'Replace old_str with new_str in an existing file. '
                'old_str must be copied exactly from the current file and match exactly once.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {'type': 'string'},
                    'old_str': {'type': 'string'},
                    'new_str': {'type': 'string'},
                    'description': {
                        'type': 'string',
                        'description': 'Updated one-sentence responsibility. Omit to keep the current description.',
                    },
                },
                'required': ['path', 'old_str', 'new_str'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'delete_file',
            'description': 'Delete one file under src/. Cannot delete App.tsx.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {'type': 'string'},
                },
                'required': ['path'],
            },
        },
    },
]


def normalize_user_path(user_path):
    path = str(user_path).replace('\\', '/').strip()
    while path.startswith('./'):
        path = path[2:]
    if path.startswith('src/'):
        path = path[4:]
    return path


def description_key(user_path):
    return 'src/' + normalize_user_path(user_path)


def safe_path(user_path):
    full = (ROOT / normalize_user_path(user_path)).resolve()
    if ROOT not in full.parents:
        raise ValueError('Path must be inside src/')
    if full.name in LOCKED and full.parent == ROOT:
        raise ValueError(full.name + ' is locked and cannot be changed')
    if full.suffix not in ('.ts', '.tsx'):
        raise ValueError('Only .ts and .tsx files are allowed')
    return full


def clean_description(value):
    if not isinstance(value, str):
        return None
    text = ' '.join(value.split())
    if text == '':
        return None
    if len(text) > MAX_DESCRIPTION_CHARS:
        text = text[:MAX_DESCRIPTION_CHARS]
    return text


def count_lines(text):
    return len(text.replace('\r\n', '\n').splitlines())


def committed_line_count(user_path):
    # The rewrite limit protects files the user already sees. Files created in this turn can be rewritten.
    committed = (COMMITTED / normalize_user_path(user_path)).resolve()
    if COMMITTED not in committed.parents or not committed.is_file():
        return 0
    return count_lines(committed.read_text(encoding='utf-8'))


def _count_component_files():
    components = ROOT / 'components'
    if not components.exists():
        return 0
    count = 0
    for path in components.rglob('*'):
        if path.is_file() and path.suffix in ('.ts', '.tsx'):
            count += 1
    return count


def with_current_text(message, full, path):
    body = full.read_text(encoding='utf-8')
    if len(body) > 8000:
        body = body[:8000] + '\n... truncated ...'
    return message + '\nCurrent text of ' + str(path) + ':\n' + body


def read_file(path):
    full = safe_path(path)
    if not full.exists():
        return 'ERROR: file does not exist'
    return full.read_text(encoding='utf-8')


def write_file(path, content, description):
    if path is None or str(path).strip() == '':
        return 'ERROR: missing argument path'
    if not isinstance(content, str):
        return 'ERROR: missing argument content'
    full = safe_path(path)
    if len(content.encode('utf-8')) > MAX_FILE_BYTES:
        return 'ERROR: file is larger than 40 KB. Split it into smaller components.'
    if full.exists():
        lines = committed_line_count(path)
        if lines > MAX_REWRITE_LINES:
            return with_current_text(
                'ERROR: ' + str(path) + ' was already in the preview and has ' + str(lines) + ' lines. '
                'Use edit_file to change only the part the user asked for.',
                full,
                path,
            )
    elif normalize_user_path(path).startswith('components/'):
        if _count_component_files() >= MAX_COMPONENT_FILES:
            return 'ERROR: at most 25 files are allowed under components/'
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding='utf-8')
    text = clean_description(description)
    if text:
        set_staged_description(description_key(path), text)
    return 'OK: wrote ' + str(path)


def find_lines_ignoring_indent(text, old_str):
    # Models often copy a snippet with different indentation. Match line by line on stripped text.
    file_lines = text.split('\n')
    wanted = []
    for line in old_str.strip('\n').split('\n'):
        wanted.append(line.strip())
    if ''.join(wanted) == '':
        return []
    hits = []
    last_start = len(file_lines) - len(wanted)
    for start in range(0, last_start + 1):
        same = True
        for offset in range(len(wanted)):
            if file_lines[start + offset].strip() != wanted[offset]:
                same = False
                break
        if same:
            hits.append(start)
    return hits


def replace_lines(text, start, count, new_str):
    file_lines = text.split('\n')
    new_lines = []
    if new_str.strip('\n') != '':
        new_lines = new_str.strip('\n').split('\n')
    return '\n'.join(file_lines[:start] + new_lines + file_lines[start + count:])


def edit_failed(message, full, path):
    if committed_line_count(path) <= MAX_REWRITE_LINES:
        message += ' Or replace the whole file with write_file.'
    return with_current_text('ERROR: ' + message, full, path)


def edit_file(path, old_str, new_str, description):
    if path is None or str(path).strip() == '':
        return 'ERROR: missing argument path'
    if not isinstance(old_str, str) or not isinstance(new_str, str):
        return 'ERROR: old_str and new_str must be strings'
    full = safe_path(path)
    if not full.exists():
        return 'ERROR: file does not exist, use write_file to create it'
    text = full.read_text(encoding='utf-8').replace('\r\n', '\n')
    if normalize_user_path(path) == 'App.tsx' and is_starter_app(text):
        return 'ERROR: src/App.tsx is still the blank starter. Replace the whole file with write_file.'
    old_str = old_str.replace('\r\n', '\n')
    new_str = new_str.replace('\r\n', '\n')
    if old_str == '':
        return edit_failed('old_str is empty. Copy a unique snippet from the current text.', full, path)
    if old_str == new_str:
        return 'OK: no change. old_str and new_str are the same, so the file was left unchanged.'
    count = text.count(old_str)
    if count > 1:
        return edit_failed('old_str matches ' + str(count) + ' places, include more surrounding lines.', full, path)
    if count == 1:
        updated = text.replace(old_str, new_str, 1)
    else:
        hits = find_lines_ignoring_indent(text, old_str)
        if len(hits) > 1:
            return edit_failed('old_str matches ' + str(len(hits)) + ' places, include more surrounding lines.', full, path)
        if len(hits) == 0:
            return edit_failed('old_str not found. Copy old_str exactly from the current text below.', full, path)
        updated = replace_lines(text, hits[0], len(old_str.strip('\n').split('\n')), new_str)
    if len(updated.encode('utf-8')) > MAX_FILE_BYTES:
        return 'ERROR: file is larger than 40 KB. Split it into smaller components.'
    full.write_text(updated, encoding='utf-8')
    text = clean_description(description)
    if text:
        set_staged_description(description_key(path), text)
    return 'OK: edited ' + str(path)


def delete_file(path):
    if path is None or str(path).strip() == '':
        return 'ERROR: missing argument path'
    full = safe_path(path)
    if full.name == 'App.tsx' and full.parent == ROOT:
        return 'ERROR: App.tsx cannot be deleted'
    if not full.exists():
        return 'ERROR: file does not exist'
    full.unlink()
    remove_staged_description(description_key(path))
    return 'OK: deleted ' + str(path)


def run_tool(name, args, changed):
    if args.get('_bad_json'):
        return 'ERROR: arguments were not valid JSON. Send the tool call again with complete arguments.'
    try:
        if name == 'read_file':
            result = read_file(args['path'])
        elif name == 'write_file':
            result = write_file(args.get('path'), args.get('content'), args.get('description'))
        elif name == 'edit_file':
            result = edit_file(args.get('path'), args.get('old_str'), args.get('new_str'), args.get('description'))
        elif name == 'delete_file':
            result = delete_file(args.get('path'))
        else:
            result = 'ERROR: unknown tool ' + str(name)
    except ValueError as err:
        return 'ERROR: ' + str(err)
    except KeyError as err:
        return 'ERROR: missing argument ' + str(err)

    if result.startswith('ERROR:') or result.startswith('OK: no change'):
        return result
    path = args.get('path')
    if path and name in ('write_file', 'edit_file', 'delete_file'):
        changed.add(normalize_user_path(path))
    return result

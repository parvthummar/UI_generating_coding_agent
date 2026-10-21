from pathlib import Path

from app.workspace import remove_staged_description, set_staged_description

REPO = Path(__file__).resolve().parents[2]
ROOT = (REPO / 'sandbox' / '.staging' / 'src').resolve()
LOCKED = ['main.tsx', 'index.css']
MAX_FILE_BYTES = 40 * 1024
MAX_COMPONENT_FILES = 25
MAX_DESCRIPTION_CHARS = 200


TOOL_DEFINITIONS = [
    {
        'type': 'function',
        'function': {
            'name': 'read_file',
            'description': (
                'Read the full source of one file under src/. '
                'The file catalog lists paths and descriptions only. '
                'Call this before edit_file, delete_file, or write_file on a file that already exists.'
            ),
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
                'Create a new file, or replace an existing file of 60 lines or fewer. '
                'Requires a one-sentence description of the file. '
                'Read an existing file with read_file before replacing it. '
                'For a localized change, use edit_file instead.'
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
                'required': ['path', 'content', 'description'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'edit_file',
            'description': (
                'Replace one exact copy of old_str with new_str in an existing file. '
                'Call read_file first and copy old_str from that text. '
                'old_str must match exactly once. '
                'Pass description only when the file responsibility changes.'
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
            'description': (
                'Delete one file under src/ that the user asked to remove, and drop its description. '
                'Cannot delete App.tsx. Call read_file first. '
                'Do not delete unrelated files.'
            ),
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


def clean_description(value, required):
    if value is None:
        if required:
            return None, 'ERROR: description is required. Say what this file is responsible for in one sentence.'
        return None, ''
    if not isinstance(value, str):
        return None, 'ERROR: description must be a string of at most 200 characters.'
    text = ' '.join(value.split())
    if text == '':
        if required:
            return None, 'ERROR: description is required. Say what this file is responsible for in one sentence.'
        return None, ''
    if len(text) > MAX_DESCRIPTION_CHARS:
        return None, 'ERROR: description must be one sentence of at most 200 characters.'
    return text, ''


def _count_component_files():
    components = ROOT / 'components'
    if not components.exists():
        return 0
    count = 0
    for path in components.rglob('*'):
        if path.is_file() and path.suffix in ('.ts', '.tsx'):
            count += 1
    return count


def _with_current_text(message, full, path):
    body = full.read_text(encoding='utf-8')
    if len(body) > 4000:
        body = body[:4000] + '\n... truncated ...'
    return message + '\nCurrent text of ' + str(path) + ':\n' + body


def _read_required(path, tool_name, seen):
    message = (
        'ERROR: call read_file on this file before '
        + tool_name
        + '. The file catalog does not include source code. '
        + 'Copy old_str from the text below if you edit, and keep the change local to the request.'
    )
    try:
        full = safe_path(path)
    except ValueError:
        return message
    if not full.exists():
        return message
    seen.add(normalize_user_path(path))
    message = _with_current_text(message, full, path)
    return message + '\nThe text above is enough for the next edit_file or write_file on this path in this turn.'


def read_file(path):
    full = safe_path(path)
    if not full.exists():
        return 'ERROR: file does not exist'
    return full.read_text(encoding='utf-8')


def write_file(path, content, description, seen):
    if path is None or str(path).strip() == '':
        return 'ERROR: missing argument path'
    if not isinstance(content, str):
        return 'ERROR: missing argument content'
    full = safe_path(path)
    text, error = clean_description(description, True)
    if error:
        return error
    if len(content.encode('utf-8')) > MAX_FILE_BYTES:
        return 'ERROR: file is larger than 40 KB'
    if full.exists():
        if normalize_user_path(path) not in seen:
            return _read_required(path, 'write_file', seen)
        existing = full.read_text(encoding='utf-8').replace('\r\n', '\n')
        line_count = len(existing.splitlines()) or (1 if existing else 0)
        if line_count > 60:
            return (
                'ERROR: this file has '
                + str(line_count)
                + ' lines. Use edit_file for a targeted change. '
                + 'write_file can only replace files of 60 lines or fewer.'
            )
    rel = normalize_user_path(path)
    is_new_component = rel.startswith('components/')
    if is_new_component and not full.exists():
        if _count_component_files() >= MAX_COMPONENT_FILES:
            return 'ERROR: at most 25 files are allowed under components/'
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding='utf-8')
    set_staged_description(description_key(path), text)
    return 'OK: wrote ' + str(path) + '. Description saved.'


def edit_file(path, old_str, new_str, description, seen):
    if path is None or str(path).strip() == '':
        return 'ERROR: missing argument path'
    if not isinstance(old_str, str) or not isinstance(new_str, str):
        return 'ERROR: old_str and new_str must be strings'
    full = safe_path(path)
    if not full.exists():
        return 'ERROR: file does not exist, use write_file to create it'
    if normalize_user_path(path) not in seen:
        return _read_required(path, 'edit_file', seen)
    updated_description, error = clean_description(description, False)
    if error:
        return error
    text = full.read_text(encoding='utf-8').replace('\r\n', '\n')
    old_str = old_str.replace('\r\n', '\n')
    new_str = new_str.replace('\r\n', '\n')
    if old_str == '':
        return 'ERROR: old_str is empty. Copy a unique snippet from read_file.'
    count = text.count(old_str)
    if count == 0:
        return _with_current_text(
            'ERROR: old_str not found. Copy a unique snippet from the current text.',
            full,
            path,
        )
    if old_str == new_str:
        return 'OK: no change. old_str and new_str are the same, so the file was left unchanged.'
    if count > 1:
        return _with_current_text(
            'ERROR: old_str matches ' + str(count) + ' places, include more surrounding lines.',
            full,
            path,
        )
    updated = text.replace(old_str, new_str, 1)
    if len(updated.encode('utf-8')) > MAX_FILE_BYTES:
        return 'ERROR: file is larger than 40 KB'
    full.write_text(updated, encoding='utf-8')
    if updated_description is not None:
        set_staged_description(description_key(path), updated_description)
    return 'OK: edited ' + str(path)


def delete_file(path, seen):
    if path is None or str(path).strip() == '':
        return 'ERROR: missing argument path'
    full = safe_path(path)
    if full.name == 'App.tsx' and full.parent == ROOT:
        return 'ERROR: App.tsx cannot be deleted'
    if not full.exists():
        return 'ERROR: file does not exist'
    if normalize_user_path(path) not in seen:
        return _read_required(path, 'delete_file', seen)
    full.unlink()
    remove_staged_description(description_key(path))
    return 'OK: deleted ' + str(path)


def run_tool(name, args, changed, seen=None):
    if seen is None:
        seen = set()
    if args.get('_bad_json'):
        return 'ERROR: arguments were not valid JSON. Send the tool call again with complete arguments.'
    try:
        if name == 'read_file':
            result = read_file(args['path'])
        elif name == 'write_file':
            result = write_file(args.get('path'), args.get('content'), args.get('description'), seen)
        elif name == 'edit_file':
            result = edit_file(
                args.get('path'),
                args.get('old_str'),
                args.get('new_str'),
                args.get('description'),
                seen,
            )
        elif name == 'delete_file':
            result = delete_file(args.get('path'), seen)
        else:
            result = 'ERROR: unknown tool ' + name
    except ValueError as err:
        return 'ERROR: ' + str(err)
    except KeyError as err:
        return 'ERROR: missing argument ' + str(err)

    if result.startswith('ERROR:'):
        return result
    path = args.get('path')
    if path and name in ('read_file', 'write_file', 'edit_file'):
        seen.add(normalize_user_path(path))
    if path and name in ('write_file', 'edit_file', 'delete_file') and not result.startswith('OK: no change'):
        changed.add(normalize_user_path(path))
    return result

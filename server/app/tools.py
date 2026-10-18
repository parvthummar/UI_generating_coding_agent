from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = (REPO / 'sandbox' / '.staging' / 'src').resolve()
LOCKED = ['main.tsx', 'index.css']
MAX_FILE_BYTES = 40 * 1024
MAX_COMPONENT_FILES = 25


TOOL_DEFINITIONS = [
    {
        'type': 'function',
        'function': {
            'name': 'read_file',
            'description': 'Read the full text of a file under src/.',
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
            'description': 'Create a new file or overwrite a short existing file (60 lines or fewer).',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {'type': 'string'},
                    'content': {'type': 'string'},
                },
                'required': ['path', 'content'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'edit_file',
            'description': 'Replace old_str with new_str in an existing file. old_str must match exactly once.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {'type': 'string'},
                    'old_str': {'type': 'string'},
                    'new_str': {'type': 'string'},
                },
                'required': ['path', 'old_str', 'new_str'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'delete_file',
            'description': 'Delete a file under src/. Cannot delete App.tsx.',
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


def safe_path(user_path):
    full = (ROOT / user_path).resolve()
    if ROOT not in full.parents:
        raise ValueError('Path must be inside src/')
    if full.name in LOCKED and full.parent == ROOT:
        raise ValueError(full.name + ' is locked and cannot be changed')
    if full.suffix not in ('.ts', '.tsx'):
        raise ValueError('Only .ts and .tsx files are allowed')
    return full


def _count_component_files():
    components = ROOT / 'components'
    if not components.exists():
        return 0
    count = 0
    for path in components.rglob('*'):
        if path.is_file() and path.suffix in ('.ts', '.tsx'):
            count += 1
    return count


def read_file(path):
    full = safe_path(path)
    if not full.exists():
        return 'ERROR: file does not exist'
    return full.read_text(encoding='utf-8')


def write_file(path, content):
    full = safe_path(path)
    if full.exists():
        existing = full.read_text(encoding='utf-8').replace('\r\n', '\n')
        line_count = len(existing.splitlines()) or (1 if existing else 0)
        if line_count > 60:
            return 'ERROR: use edit_file for this file'
    if len(content.encode('utf-8')) > MAX_FILE_BYTES:
        return 'ERROR: file is larger than 40 KB'
    rel = str(path).replace('\\', '/')
    is_new_component = rel.startswith('components/') or '/components/' in rel
    if is_new_component and not full.exists():
        if _count_component_files() >= MAX_COMPONENT_FILES:
            return 'ERROR: at most 25 files are allowed under components/'
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding='utf-8')
    return 'OK: wrote ' + path


def edit_file(path, old_str, new_str):
    full = safe_path(path)
    if not full.exists():
        return 'ERROR: file does not exist, use write_file to create it'
    text = full.read_text(encoding='utf-8').replace('\r\n', '\n')
    old_str = old_str.replace('\r\n', '\n')
    new_str = new_str.replace('\r\n', '\n')
    count = text.count(old_str)
    if count == 0:
        return 'ERROR: old_str not found, use read_file to see the current text'
    if count > 1:
        return 'ERROR: old_str matches ' + str(count) + ' places, include more surrounding lines'
    updated = text.replace(old_str, new_str)
    if len(updated.encode('utf-8')) > MAX_FILE_BYTES:
        return 'ERROR: file is larger than 40 KB'
    full.write_text(updated, encoding='utf-8')
    return 'OK: edited ' + path


def delete_file(path):
    full = safe_path(path)
    if full.name == 'App.tsx' and full.parent == ROOT:
        return 'ERROR: App.tsx cannot be deleted'
    if not full.exists():
        return 'ERROR: file does not exist'
    full.unlink()
    return 'OK: deleted ' + path


def run_tool(name, args, changed):
    if args.get('_bad_json'):
        return 'ERROR: arguments were not valid JSON'
    try:
        if name == 'read_file':
            result = read_file(args['path'])
        elif name == 'write_file':
            result = write_file(args['path'], args['content'])
        elif name == 'edit_file':
            result = edit_file(args['path'], args['old_str'], args['new_str'])
        elif name == 'delete_file':
            result = delete_file(args['path'])
        else:
            result = 'ERROR: unknown tool ' + name
    except ValueError as err:
        return 'ERROR: ' + str(err)
    except KeyError as err:
        return 'ERROR: missing argument ' + str(err)

    if not result.startswith('ERROR:') and name in ('write_file', 'edit_file', 'delete_file'):
        path = args.get('path')
        if path:
            changed.add(path.replace('\\', '/'))
    return result

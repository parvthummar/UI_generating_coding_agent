from pathlib import Path

from app.catalog import STAGING_CATALOG, lookup_description, normalize_description, remove_description, set_description

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
            'description': 'Read the full source of one file under src/. The result includes the stored description and the file text.',
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
            'description': 'Create a new file or overwrite a short existing file (60 lines or fewer). When creating a file, description is required and must be one sentence about that file. When overwriting, omit description to keep the current one.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {'type': 'string'},
                    'content': {'type': 'string'},
                    'description': {'type': 'string'},
                },
                'required': ['path', 'content'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'edit_file',
            'description': 'Replace old_str with new_str in an existing file. old_str must match exactly once. Pass description only when the file responsibility changes; omit it to keep the current description.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {'type': 'string'},
                    'old_str': {'type': 'string'},
                    'new_str': {'type': 'string'},
                    'description': {'type': 'string'},
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


def normalize_user_path(user_path):
    path = str(user_path).replace('\\', '/').strip()
    while path.startswith('./'):
        path = path[2:]
    if path.startswith('src/'):
        path = path[4:]
    return path


def safe_path(user_path):
    full = (ROOT / normalize_user_path(user_path)).resolve()
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


def file_key(user_path):
    return 'src/' + normalize_user_path(user_path)


def read_file(path):
    full = safe_path(path)
    if not full.exists():
        return 'ERROR: file does not exist'
    description = lookup_description(STAGING_CATALOG, file_key(path))
    text = full.read_text(encoding='utf-8')
    return 'Description: ' + description + '\n\n' + text


def write_file(path, content, description=None):
    full = safe_path(path)
    is_new = not full.exists()
    if not is_new:
        existing = full.read_text(encoding='utf-8').replace('\r\n', '\n')
        line_count = len(existing.splitlines()) or (1 if existing else 0)
        if line_count > 60:
            return 'ERROR: use edit_file for this file'
    if len(content.encode('utf-8')) > MAX_FILE_BYTES:
        return 'ERROR: file is larger than 40 KB'
    rel = normalize_user_path(path)
    is_new_component = rel.startswith('components/')
    if is_new_component and is_new:
        if _count_component_files() >= MAX_COMPONENT_FILES:
            return 'ERROR: at most 25 files are allowed under components/'
    text, err = normalize_description(description, is_new)
    if err:
        return err
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding='utf-8')
    if text is not None:
        set_description(STAGING_CATALOG, file_key(path), text)
    return 'OK: wrote ' + path


def edit_file(path, old_str, new_str, description=None):
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
    new_description, err = normalize_description(description, False)
    if err:
        return err
    full.write_text(updated, encoding='utf-8')
    if new_description is not None:
        set_description(STAGING_CATALOG, file_key(path), new_description)
    return 'OK: edited ' + path


def delete_file(path):
    full = safe_path(path)
    if full.name == 'App.tsx' and full.parent == ROOT:
        return 'ERROR: App.tsx cannot be deleted'
    if not full.exists():
        return 'ERROR: file does not exist'
    key = file_key(path)
    full.unlink()
    remove_description(STAGING_CATALOG, key)
    return 'OK: deleted ' + path


def run_tool(name, args, changed):
    if args.get('_bad_json'):
        return 'ERROR: arguments were not valid JSON'
    try:
        if name == 'read_file':
            result = read_file(args['path'])
        elif name == 'write_file':
            result = write_file(args['path'], args['content'], args.get('description'))
        elif name == 'edit_file':
            result = edit_file(args['path'], args['old_str'], args['new_str'], args.get('description'))
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
            changed.add(normalize_user_path(path))
    return result

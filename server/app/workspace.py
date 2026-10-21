import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SANDBOX_SRC = REPO / 'sandbox' / 'src'
STAGING = REPO / 'sandbox' / '.staging'
STAGING_SRC = STAGING / 'src'
SNAPSHOTS = REPO / 'sandbox' / '.snapshots'
MAX_SNAPSHOTS = 20
TEMPLATE_APP = REPO / 'server' / 'template' / 'src' / 'App.tsx'
STAGING_TSCONFIG = STAGING / 'tsconfig.json'
# Kept outside src/ so the catalog is not a generated source file and Vite does not treat it as UI.
SANDBOX_DESCRIPTIONS = REPO / 'sandbox' / 'file_descriptions.json'
STAGING_DESCRIPTIONS = STAGING / 'file_descriptions.json'
DESCRIPTION_NAME = 'file_descriptions.json'

STARTER_DESCRIPTIONS = {
    'src/App.tsx': 'Starter screen with a default export named App. Replace this when creating a new UI.',
    'src/main.tsx': 'Locked preview entry. Mounts App and reports runtime crashes. Do not edit.',
    'src/index.css': 'Locked Tailwind stylesheet. Do not edit.',
    'src/vite-env.d.ts': 'Vite client types. Not a UI component.',
}

STAGING_TSCONFIG_TEXT = '''{
  "extends": "../tsconfig.json",
  "include": ["src"]
}
'''


def ensure_staging_layout():
    STAGING.mkdir(parents=True, exist_ok=True)
    STAGING_SRC.mkdir(parents=True, exist_ok=True)
    STAGING_TSCONFIG.write_text(STAGING_TSCONFIG_TEXT, encoding='utf-8')
    index = REPO / 'sandbox' / 'index.html'
    if index.exists():
        (STAGING / 'index.html').write_text(index.read_text(encoding='utf-8'), encoding='utf-8')


def _copy_tree(src: Path, dest: Path):
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def reset_staging_from_sandbox():
    ensure_staging_layout()
    _copy_tree(SANDBOX_SRC, STAGING_SRC)
    sync_description_file(SANDBOX_SRC, SANDBOX_DESCRIPTIONS)
    _copy_description_file(SANDBOX_DESCRIPTIONS, STAGING_DESCRIPTIONS)


def _snapshot_names():
    if not SNAPSHOTS.exists():
        return []
    names = []
    for path in SNAPSHOTS.iterdir():
        if path.is_dir() and path.name.isdigit():
            names.append(path.name)
    names.sort()
    return names


def clear_snapshots():
    if SNAPSHOTS.exists():
        shutil.rmtree(SNAPSHOTS)


def snapshot_committed():
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    names = _snapshot_names()
    number = 1
    if names:
        number = int(names[-1]) + 1
    dest_root = SNAPSHOTS / str(number).zfill(4)
    dest_root.mkdir(parents=True, exist_ok=True)
    _copy_tree(SANDBOX_SRC, dest_root / 'src')
    _copy_description_file(SANDBOX_DESCRIPTIONS, dest_root / DESCRIPTION_NAME)
    names = _snapshot_names()
    while len(names) > MAX_SNAPSHOTS:
        shutil.rmtree(SNAPSHOTS / names[0])
        names = names[1:]


def snapshot_count():
    return len(_snapshot_names())


def undo_committed():
    names = _snapshot_names()
    if not names:
        return None
    latest = names[-1]
    saved = SNAPSHOTS / latest / 'src'
    _copy_tree(saved, SANDBOX_SRC)
    _copy_description_file(SNAPSHOTS / latest / DESCRIPTION_NAME, SANDBOX_DESCRIPTIONS)
    shutil.rmtree(SNAPSHOTS / latest)
    reset_staging_from_sandbox()
    return read_committed_files()


def commit_staging_to_sandbox():
    ensure_staging_layout()
    sync_description_file(STAGING_SRC, STAGING_DESCRIPTIONS)
    snapshot_committed()
    staging_files = _list_src_files(STAGING_SRC)
    sandbox_files = _list_src_files(SANDBOX_SRC)

    for rel in staging_files:
        source = STAGING_SRC / rel
        target = SANDBOX_SRC / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding='utf-8'), encoding='utf-8')

    for rel in sandbox_files:
        if rel not in staging_files:
            (SANDBOX_SRC / rel).unlink(missing_ok=True)

    _remove_empty_dirs(SANDBOX_SRC)
    _copy_description_file(STAGING_DESCRIPTIONS, SANDBOX_DESCRIPTIONS)


def read_committed_files():
    result = {}
    for rel in sorted(_list_src_files(SANDBOX_SRC)):
        key = 'src/' + rel.replace('\\', '/')
        result[key] = (SANDBOX_SRC / rel).read_text(encoding='utf-8')
    return result


def _list_src_files(root: Path):
    files = set()
    if not root.exists():
        return files
    for path in root.rglob('*'):
        if path.is_file() and path.suffix in ('.ts', '.tsx', '.css'):
            files.add(str(path.relative_to(root)).replace('\\', '/'))
    return files


def _remove_empty_dirs(root: Path):
    if not root.exists():
        return
    for path in sorted(root.rglob('*'), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass


def is_starter_app(text):
    starter = TEMPLATE_APP.read_text(encoding='utf-8').replace('\r\n', '\n').strip()
    return text.replace('\r\n', '\n').strip() == starter


def apply_template_app():
    clear_snapshots()
    SANDBOX_SRC.mkdir(parents=True, exist_ok=True)
    components = SANDBOX_SRC / 'components'
    if components.exists():
        shutil.rmtree(components)
    text = TEMPLATE_APP.read_text(encoding='utf-8')
    (SANDBOX_SRC / 'App.tsx').write_text(text, encoding='utf-8')
    write_description_map(SANDBOX_DESCRIPTIONS, STARTER_DESCRIPTIONS)
    ensure_staging_layout()
    reset_staging_from_sandbox()


def project_files(src_root):
    found = []
    if not src_root.exists():
        return found
    for path in src_root.rglob('*'):
        if not path.is_file():
            continue
        if path.suffix not in ('.ts', '.tsx', '.css'):
            continue
        if path.name == DESCRIPTION_NAME:
            continue
        rel = 'src/' + str(path.relative_to(src_root)).replace('\\', '/')
        if '..' in rel.split('/'):
            continue
        found.append(rel)
    found.sort()
    return found


def read_description_map(path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    clean = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        name = key.replace('\\', '/').strip()
        if not name.startswith('src/') or '..' in name.split('/'):
            continue
        if name.endswith('/' + DESCRIPTION_NAME) or name == 'src/' + DESCRIPTION_NAME:
            continue
        text = ' '.join(value.split())
        if text == '':
            continue
        clean[name] = text
    return clean


def write_description_map(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {}
    for key in sorted(data):
        ordered[key] = data[key]
    path.write_text(json.dumps(ordered, indent=2) + '\n', encoding='utf-8')


def sync_description_file(src_root, desc_path):
    existing = set(project_files(src_root))
    current = read_description_map(desc_path)
    cleaned = {}
    for name in sorted(existing):
        value = current.get(name, '')
        if value:
            cleaned[name] = value
    write_description_map(desc_path, cleaned)
    return cleaned


def set_staged_description(key, text):
    cleaned = sync_description_file(STAGING_SRC, STAGING_DESCRIPTIONS)
    if key not in project_files(STAGING_SRC):
        return
    cleaned[key] = text
    write_description_map(STAGING_DESCRIPTIONS, cleaned)


def remove_staged_description(key):
    cleaned = sync_description_file(STAGING_SRC, STAGING_DESCRIPTIONS)
    if key in cleaned:
        del cleaned[key]
        write_description_map(STAGING_DESCRIPTIONS, cleaned)


def _copy_description_file(src, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        dest.write_text(src.read_text(encoding='utf-8'), encoding='utf-8')
    else:
        dest.write_text('{}\n', encoding='utf-8')

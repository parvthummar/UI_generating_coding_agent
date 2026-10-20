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

STAGING_TSCONFIG_TEXT = '''{
  "extends": "../tsconfig.json",
  "include": ["src"]
}
'''


def ensure_staging_layout():
    STAGING.mkdir(parents=True, exist_ok=True)
    STAGING_SRC.mkdir(parents=True, exist_ok=True)
    STAGING_TSCONFIG.write_text(STAGING_TSCONFIG_TEXT, encoding='utf-8')


def _copy_tree(src: Path, dest: Path):
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def reset_staging_from_sandbox():
    ensure_staging_layout()
    _copy_tree(SANDBOX_SRC, STAGING_SRC)


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
    shutil.rmtree(SNAPSHOTS / latest)
    reset_staging_from_sandbox()
    return read_committed_files()


def commit_staging_to_sandbox():
    ensure_staging_layout()
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


def apply_template_app():
    clear_snapshots()
    SANDBOX_SRC.mkdir(parents=True, exist_ok=True)
    components = SANDBOX_SRC / 'components'
    if components.exists():
        shutil.rmtree(components)
    text = TEMPLATE_APP.read_text(encoding='utf-8')
    (SANDBOX_SRC / 'App.tsx').write_text(text, encoding='utf-8')
    ensure_staging_layout()
    reset_staging_from_sandbox()

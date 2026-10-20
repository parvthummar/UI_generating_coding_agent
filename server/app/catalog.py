import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COMMITTED_CATALOG = REPO / 'server' / 'data' / 'catalog.json'
STAGING_CATALOG = REPO / 'sandbox' / '.staging' / 'catalog.json'
MAX_DESCRIPTION_CHARS = 400
FALLBACK_DESCRIPTION = 'Fallback description: purpose was not recorded for this file.'

STARTER_DESCRIPTIONS = {
    'src/App.tsx': 'Root React component that renders the starter screen as a full-height white page.',
    'src/main.tsx': 'Locked preview entry that mounts App inside an error boundary and reports runtime errors to the host page.',
    'src/index.css': 'Locked global stylesheet that loads Tailwind and makes the html, body, and root elements fill the viewport.',
    'src/vite-env.d.ts': 'TypeScript reference that loads Vite client types for the preview project.',
}


def load_catalog(path: Path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_catalog(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {}
    for key in sorted(data):
        entry = data[key]
        if not isinstance(entry, dict):
            continue
        text = entry.get('description')
        if not isinstance(text, str):
            continue
        text = text.strip()
        if text == '':
            continue
        ordered[key] = {'description': text}
    path.write_text(json.dumps(ordered, indent=2) + '\n', encoding='utf-8')


def list_source_keys(src_root: Path):
    keys = []
    if not src_root.exists():
        return keys
    for path in src_root.rglob('*'):
        if path.is_file() and path.suffix in ('.ts', '.tsx', '.css'):
            rel = str(path.relative_to(src_root)).replace('\\', '/')
            keys.append('src/' + rel)
    keys.sort()
    return keys


def description_for(key, stored):
    entry = stored.get(key)
    if isinstance(entry, dict):
        text = entry.get('description')
        if isinstance(text, str) and text.strip():
            return text.strip()
    if key in STARTER_DESCRIPTIONS:
        return STARTER_DESCRIPTIONS[key]
    return FALLBACK_DESCRIPTION


def reconciled_entries(src_root: Path, catalog_path: Path, overrides=None):
    stored = load_catalog(catalog_path)
    if overrides:
        for key in overrides:
            stored[key] = overrides[key]
    result = {}
    for key in list_source_keys(src_root):
        result[key] = {'description': description_for(key, stored)}
    return result


def catalog_view(src_root: Path, catalog_path: Path):
    return reconciled_entries(src_root, catalog_path)


def lookup_description(catalog_path: Path, key):
    return description_for(key, load_catalog(catalog_path))


def set_description(catalog_path: Path, key, description):
    data = load_catalog(catalog_path)
    data[key] = {'description': description.strip()}
    save_catalog(catalog_path, data)


def remove_description(catalog_path: Path, key):
    data = load_catalog(catalog_path)
    if key not in data:
        return
    del data[key]
    save_catalog(catalog_path, data)


def normalize_description(description, required):
    if description is None:
        if required:
            return None, 'ERROR: description is required when creating a file'
        return None, None
    if not isinstance(description, str):
        return None, 'ERROR: description must be a non-empty string'
    text = description.strip()
    if text == '':
        if required:
            return None, 'ERROR: description is required when creating a file'
        return None, 'ERROR: description cannot be empty'
    if len(text) > MAX_DESCRIPTION_CHARS:
        return None, 'ERROR: description must be one short sentence'
    return text, None

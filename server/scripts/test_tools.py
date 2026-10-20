from pathlib import Path

from app import tools, validate, workspace
from app.agent import build_user_message, run_turn
from app.catalog import COMMITTED_CATALOG, FALLBACK_DESCRIPTION, STAGING_CATALOG, STARTER_DESCRIPTIONS
from app.prompts import SYSTEM_PROMPT
from app.sessions import Session

NL = '\n'
PASS = 0
FAIL = 0


def check(name, ok, detail=''):
    global PASS, FAIL
    if ok:
        PASS += 1
        print('PASS: ' + name)
    else:
        FAIL += 1
        extra = ''
        if detail:
            extra = ' — ' + detail
        print('FAIL: ' + name + extra)


def main():
    workspace.apply_template_app()
    changed = set()

    # Paths that include the src/ prefix still land inside src/
    result = tools.run_tool(
        'write_file',
        {
            'path': 'src/components/FromSrc.tsx',
            'content': 'export const fromSrc = 1;\n',
            'description': 'Exports a constant used to check the src/ path prefix.',
        },
        changed,
    )
    from_src = workspace.STAGING_SRC / 'components' / 'FromSrc.tsx'
    nested = workspace.STAGING_SRC / 'src' / 'components' / 'FromSrc.tsx'
    check('src/ prefix stays inside src', result.startswith('OK:') and from_src.exists() and not nested.exists(), result)

    # Creating a file works
    result = tools.run_tool(
        'write_file',
        {
            'path': 'components/Hello.tsx',
            'content': 'export default function Hello() { return <div>Hi</div>; }\n',
            'description': 'Renders a small hello message.',
        },
        changed,
    )
    check('creating a file works', result.startswith('OK:'), result)

    # Missing old_str returns an error
    result = tools.run_tool(
        'edit_file',
        {'path': 'components/Hello.tsx', 'old_str': 'this string is not in the file', 'new_str': 'x'},
        changed,
    )
    check('missing old_str returns an error', result.startswith('ERROR:') and 'not found' in result, result)

    # Duplicate old_str returns an error
    tools.run_tool(
        'write_file',
        {
            'path': 'components/Dup.tsx',
            'content': 'const a = 1;\nconst a = 1;\n',
            'description': 'Holds a duplicated string so edit matching can be checked.',
        },
        changed,
    )
    result = tools.run_tool(
        'edit_file',
        {'path': 'components/Dup.tsx', 'old_str': 'const a = 1;', 'new_str': 'const a = 2;'},
        changed,
    )
    check('duplicate old_str returns an error', result.startswith('ERROR:') and 'matches' in result, result)

    # ../x is rejected
    result = tools.run_tool('write_file', {'path': '../x.tsx', 'content': 'export {};\n'}, changed)
    check('../x is rejected', result.startswith('ERROR:') and 'inside src' in result, result)

    # Writing main.tsx is rejected
    result = tools.run_tool('write_file', {'path': 'main.tsx', 'content': 'export {};\n'}, changed)
    check('writing main.tsx is rejected', result.startswith('ERROR:') and 'locked' in result, result)

    # Overwriting a long existing file is rejected
    long_text = NL.join(['const n' + str(i) + ' = ' + str(i) + ';' for i in range(70)]) + NL
    tools.run_tool(
        'write_file',
        {
            'path': 'components/Long.tsx',
            'content': long_text,
            'description': 'Holds many const bindings so overwrite protection can be checked.',
        },
        changed,
    )
    result = tools.run_tool(
        'write_file',
        {'path': 'components/Long.tsx', 'content': 'export {};\n'},
        changed,
    )
    check(
        'overwriting a long existing file is rejected',
        result.startswith('ERROR:') and 'edit_file' in result,
        result,
    )

    # Template compiles clean (reset staging from sandbox first with clean App)
    workspace.apply_template_app()
    errors = validate.run_tsc()
    check('the template compiles clean', errors == '', errors[:300] if errors else '')

    # After writing a type error, the compiler reports an error
    workspace.reset_staging_from_sandbox()
    bad = "const x: number = 'a';\nexport default function App() { return <div>{x}</div>; }\n"
    tools.run_tool('write_file', {'path': 'App.tsx', 'content': bad}, set())
    errors = validate.run_tsc()
    check('compiler reports an error for bad types', errors != '', errors[:300])

    # Commit copies files
    workspace.apply_template_app()
    workspace.reset_staging_from_sandbox()
    tools.run_tool(
        'write_file',
        {
            'path': 'components/Committed.tsx',
            'content': 'export const marker = "committed-ok";\n',
            'description': 'Marks a file copied from staging on commit.',
        },
        set(),
    )
    workspace.commit_staging_to_sandbox()
    committed = workspace.SANDBOX_SRC / 'components' / 'Committed.tsx'
    check('commit copies files', committed.exists() and 'committed-ok' in committed.read_text(encoding='utf-8'))

    # Rollback restores
    workspace.reset_staging_from_sandbox()
    tools.run_tool(
        'write_file',
        {
            'path': 'components/TempOnly.tsx',
            'content': 'export const temp = 1;\n',
            'description': 'Temporary component that rollback should discard.',
        },
        set(),
    )
    staging_temp = workspace.STAGING_SRC / 'components' / 'TempOnly.tsx'
    check('staging has temp file before rollback', staging_temp.exists())
    workspace.reset_staging_from_sandbox()
    check('rollback restores', not staging_temp.exists())
    check(
        'rollback leaves committed files',
        committed.exists() and not (workspace.SANDBOX_SRC / 'components' / 'TempOnly.tsx').exists(),
    )

    # A rolled-back generation must not let the next request edit the preview.
    workspace.apply_template_app()
    before = workspace.read_committed_files()
    blocked = Session()
    blocked.mark_rolled_back('Finance dashboard with summary cards')
    blocked_events = ''.join(list(run_turn(blocked, 'Add a dark mode toggle in the header')))
    check('failed generation blocks follow-up', 'followup_blocked' in blocked_events)
    check('blocked follow-up does not change preview', workspace.read_committed_files() == before)
    committed_note = build_user_message('hello', False, '')
    check('committed state is explicit', 'COMMITTED PREVIEW' in committed_note)
    failed_note = build_user_message('hello', True, 'Finance dashboard')
    check('rolled back request is named', 'FAILED and was rolled back' in failed_note and 'Finance dashboard' in failed_note)

    # Undo restores the previous committed source.
    workspace.apply_template_app()
    original = (workspace.SANDBOX_SRC / 'App.tsx').read_text(encoding='utf-8')
    workspace.reset_staging_from_sandbox()
    tools.run_tool(
        'write_file',
        {
            'path': 'App.tsx',
            'content': 'export default function App() { return <div>Changed</div>; }\n',
            'description': 'Temporary root that shows the word Changed.',
        },
        set(),
    )
    workspace.commit_staging_to_sandbox()
    changed_text = (workspace.SANDBOX_SRC / 'App.tsx').read_text(encoding='utf-8')
    check('commit saves a snapshot', 'Changed' in changed_text and workspace.snapshot_count() == 1)
    restored = workspace.undo_committed()
    restored_text = (workspace.SANDBOX_SRC / 'App.tsx').read_text(encoding='utf-8')
    check('undo restores the previous UI', restored is not None and restored_text == original and 'Changed' not in restored_text)
    undone = workspace.read_committed_catalog()
    check(
        'undo restores the previous description',
        undone['src/App.tsx']['description'] == STARTER_DESCRIPTIONS['src/App.tsx'],
        undone['src/App.tsx']['description'],
    )
    check('undo with no snapshot returns nothing', workspace.undo_committed() is None)

    vite_config = (workspace.REPO / 'sandbox' / 'vite.config.ts').read_text(encoding='utf-8')
    check(
        'preview CSP blocks remote network',
        "connect-src 'self'" in vite_config and 'frame-ancestors http://localhost:5173' in vite_config and 'https:' not in vite_config,
    )
    check('preview cannot serve the parent repo', 'allow: [sandboxRoot]' in vite_config and 'envDir: sandboxRoot' in vite_config)
    client_app = (workspace.REPO / 'client' / 'src' / 'App.tsx').read_text(encoding='utf-8')
    check(
        'iframe stays sandboxed',
        'sandbox="allow-scripts allow-same-origin allow-modals"' in client_app and 'referrerPolicy="no-referrer"' in client_app,
    )
    check(
        'runtime crash can be sent for repair',
        'The preview compiled, then crashed at runtime.' in client_app and 'Ask the agent to fix this' in client_app,
    )
    sandbox_main = (workspace.REPO / 'sandbox' / 'src' / 'main.tsx').read_text(encoding='utf-8')
    check('runtime errors are reported to the host', "type: 'SANDBOX_RUNTIME_ERROR'" in sandbox_main)

    catalog_checks()

    # Leave sandbox clean for the running preview
    workspace.apply_template_app()

    print(NL + 'Result: ' + str(PASS) + ' passed, ' + str(FAIL) + ' failed')
    if FAIL:
        raise SystemExit(1)


def tool_schema(name):
    for item in tools.TOOL_DEFINITIONS:
        if item['function']['name'] == name:
            return item['function']
    return None


def catalog_checks():
    names = [item['function']['name'] for item in tools.TOOL_DEFINITIONS]
    check('tool count stays at four', names == ['read_file', 'write_file', 'edit_file', 'delete_file'])
    check('write_file schema has description', 'description' in tool_schema('write_file')['parameters']['properties'])
    check('edit_file schema has description', 'description' in tool_schema('edit_file')['parameters']['properties'])
    check('delete_file schema has no description', 'description' not in tool_schema('delete_file')['parameters']['properties'])
    check(
        'system prompt tells the model to read before editing',
        'file catalog' in SYSTEM_PROMPT and 'Call read_file' in SYSTEM_PROMPT and 'before editing' in SYSTEM_PROMPT,
    )

    workspace.apply_template_app()
    committed = workspace.read_committed_files()
    catalog = workspace.read_committed_catalog()
    missing = []
    for path in committed:
        entry = catalog.get(path)
        if not entry or not str(entry.get('description', '')).strip():
            missing.append(path)
        elif entry['description'] == FALLBACK_DESCRIPTION:
            missing.append(path)
        elif '..' in path or not path.startswith('src/'):
            missing.append(path)
    check('starter source files have catalog entries', missing == [], ', '.join(missing))
    check('catalog is outside the preview source tree', workspace.SANDBOX_SRC not in COMMITTED_CATALOG.parents)
    check('staged catalog is outside staged source', workspace.STAGING_SRC not in STAGING_CATALOG.parents)

    starter_note = build_user_message('Add a dark mode toggle to the header')
    app_source = (workspace.SANDBOX_SRC / 'App.tsx').read_text(encoding='utf-8')
    main_source = (workspace.SANDBOX_SRC / 'main.tsx').read_text(encoding='utf-8')
    check('starter prompt lists paths and descriptions', 'src/App.tsx — ' in starter_note and 'src/main.tsx — ' in starter_note)
    check('starter prompt does not dump source', app_source not in starter_note and 'SANDBOX_RUNTIME_ERROR' not in starter_note and main_source not in starter_note)
    check('starter prompt requires read_file before editing', 'Call read_file on an existing file before editing it.' in starter_note)

    orphan = workspace.SANDBOX_SRC / 'components' / 'Orphan.tsx'
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text('export const orphan = 1;\n', encoding='utf-8')
    fallback_note = build_user_message('inspect the orphan')
    check(
        'missing description uses a labeled fallback',
        'src/components/Orphan.tsx — ' + FALLBACK_DESCRIPTION in fallback_note,
    )
    workspace.apply_template_app()

    created = tools.run_tool(
        'write_file',
        {
            'path': 'components/Note.tsx',
            'content': 'export const note = "catalog-note";\n',
            'description': 'Exports a note used by the catalog tests.',
        },
        set(),
    )
    check('write_file saves the description in staging', created.startswith('OK:'))
    staged_catalog = json_catalog(STAGING_CATALOG)
    check(
        'staged description matches the write',
        staged_catalog.get('src/components/Note.tsx', {}).get('description') == 'Exports a note used by the catalog tests.',
    )
    check('new file description is not committed yet', 'src/components/Note.tsx' not in json_catalog(COMMITTED_CATALOG))

    missing_description = tools.run_tool(
        'write_file',
        {'path': 'components/NoDesc.tsx', 'content': 'export const missing = 1;\n'},
        set(),
    )
    check(
        'write_file requires a description for a new file',
        missing_description.startswith('ERROR:') and 'description' in missing_description,
        missing_description,
    )
    check('rejected write does not create a file', not (workspace.STAGING_SRC / 'components' / 'NoDesc.tsx').exists())

    edited = tools.run_tool(
        'edit_file',
        {
            'path': 'components/Note.tsx',
            'old_str': 'catalog-note',
            'new_str': 'catalog-edited',
        },
        set(),
    )
    after_edit = json_catalog(STAGING_CATALOG)
    check('edit_file keeps the description when omitted', edited.startswith('OK:') and after_edit['src/components/Note.tsx']['description'] == 'Exports a note used by the catalog tests.')

    renamed = tools.run_tool(
        'edit_file',
        {
            'path': 'components/Note.tsx',
            'old_str': 'catalog-edited',
            'new_str': 'catalog-renamed',
            'description': 'Exports the renamed catalog test marker.',
        },
        set(),
    )
    after_rename = json_catalog(STAGING_CATALOG)
    check(
        'edit_file updates the description when one is provided',
        renamed.startswith('OK:') and after_rename['src/components/Note.tsx']['description'] == 'Exports the renamed catalog test marker.',
    )

    read_back = tools.run_tool('read_file', {'path': 'components/Note.tsx'}, set())
    check(
        'read_file returns the file source',
        'export const note = "catalog-renamed";' in read_back and read_back.strip().endswith('export const note = "catalog-renamed";'),
        read_back,
    )
    check('read_file includes the stored description', 'Exports the renamed catalog test marker.' in read_back)

    removed = tools.run_tool('delete_file', {'path': 'components/Note.tsx'}, set())
    after_delete = json_catalog(STAGING_CATALOG)
    check('delete_file removes the catalog entry', removed.startswith('OK:') and 'src/components/Note.tsx' not in after_delete)

    kept = tools.run_tool('delete_file', {'path': 'App.tsx'}, set())
    after_kept = json_catalog(STAGING_CATALOG)
    check('delete_file still refuses App.tsx', kept.startswith('ERROR:') and 'App.tsx' in kept)
    check('refused delete keeps the App description', after_kept['src/App.tsx']['description'] == STARTER_DESCRIPTIONS['src/App.tsx'])

    blocked_path = tools.run_tool('write_file', {'path': '../outside.tsx', 'content': 'export {};\n', 'description': 'Should not be stored.'}, set())
    check('invalid catalog path is still rejected', blocked_path.startswith('ERROR:') and 'inside src' in blocked_path, blocked_path)
    check('rejected path is not added to the catalog', 'src/../outside.tsx' not in json_catalog(STAGING_CATALOG))

    locked = tools.run_tool('write_file', {'path': 'main.tsx', 'content': 'export {};\n', 'description': 'Should not replace the entry.'}, set())
    check('locked file is still rejected', locked.startswith('ERROR:') and 'locked' in locked, locked)

    before_commit = COMMITTED_CATALOG.read_text(encoding='utf-8')
    workspace.reset_staging_from_sandbox()
    tools.run_tool(
        'write_file',
        {
            'path': 'components/RolledBack.tsx',
            'content': 'export const rolled = 1;\n',
            'description': 'Should disappear when the turn is rolled back.',
        },
        set(),
    )
    check('failed staging does not change the committed catalog', COMMITTED_CATALOG.read_text(encoding='utf-8') == before_commit)
    workspace.reset_staging_from_sandbox()
    check('rollback drops the staged description', 'src/components/RolledBack.tsx' not in workspace.read_committed_catalog())
    check('rollback drops the staged file', not (workspace.SANDBOX_SRC / 'components' / 'RolledBack.tsx').exists())

    workspace.reset_staging_from_sandbox()
    tools.run_tool(
        'write_file',
        {
            'path': 'components/Kept.tsx',
            'content': 'export const keptMarker = "kept-body";\n',
            'description': 'Component created by the agent and stored in the catalog.',
        },
        set(),
    )
    workspace.commit_staging_to_sandbox()
    kept_catalog = workspace.read_committed_catalog()
    kept_note = build_user_message('change the kept marker')
    check(
        'commit stores the matching description',
        kept_catalog['src/components/Kept.tsx']['description'] == 'Component created by the agent and stored in the catalog.',
    )
    check('prompt lists the agent-created file', 'src/components/Kept.tsx — Component created by the agent and stored in the catalog.' in kept_note)
    check('prompt omits the agent-created source', 'keptMarker' not in kept_note and 'kept-body' not in kept_note)

    workspace.reset_staging_from_sandbox()
    tools.run_tool('delete_file', {'path': 'components/Kept.tsx'}, set())
    workspace.commit_staging_to_sandbox()
    check('committed delete removes the description', 'src/components/Kept.tsx' not in workspace.read_committed_catalog())
    check('committed delete removes the file', not (workspace.SANDBOX_SRC / 'components' / 'Kept.tsx').exists())

    workspace.apply_template_app()
    check('new session clears generated descriptions', 'src/components/Kept.tsx' not in workspace.read_committed_catalog())
    check(
        'new session restores the starter description',
        workspace.read_committed_catalog()['src/App.tsx']['description'] == STARTER_DESCRIPTIONS['src/App.tsx'],
    )


def json_catalog(path):
    import json
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    main()

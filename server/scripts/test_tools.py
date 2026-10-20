from pathlib import Path

from app import tools, validate, workspace
from app.agent import build_user_message, run_turn
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
        {'path': 'src/components/FromSrc.tsx', 'content': 'export const fromSrc = 1;\n'},
        changed,
    )
    from_src = workspace.STAGING_SRC / 'components' / 'FromSrc.tsx'
    nested = workspace.STAGING_SRC / 'src' / 'components' / 'FromSrc.tsx'
    check('src/ prefix stays inside src', result.startswith('OK:') and from_src.exists() and not nested.exists(), result)

    # Creating a file works
    result = tools.run_tool(
        'write_file',
        {'path': 'components/Hello.tsx', 'content': 'export default function Hello() { return <div>Hi</div>; }\n'},
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
        {'path': 'components/Dup.tsx', 'content': 'const a = 1;\nconst a = 1;\n'},
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
    tools.run_tool('write_file', {'path': 'components/Long.tsx', 'content': long_text}, changed)
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
        {'path': 'components/Committed.tsx', 'content': 'export const marker = "committed-ok";\n'},
        set(),
    )
    workspace.commit_staging_to_sandbox()
    committed = workspace.SANDBOX_SRC / 'components' / 'Committed.tsx'
    check('commit copies files', committed.exists() and 'committed-ok' in committed.read_text(encoding='utf-8'))

    # Rollback restores
    workspace.reset_staging_from_sandbox()
    tools.run_tool(
        'write_file',
        {'path': 'components/TempOnly.tsx', 'content': 'export const temp = 1;\n'},
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
        {'path': 'App.tsx', 'content': 'export default function App() { return <div>Changed</div>; }\n'},
        set(),
    )
    workspace.commit_staging_to_sandbox()
    changed_text = (workspace.SANDBOX_SRC / 'App.tsx').read_text(encoding='utf-8')
    check('commit saves a snapshot', 'Changed' in changed_text and workspace.snapshot_count() == 1)
    restored = workspace.undo_committed()
    restored_text = (workspace.SANDBOX_SRC / 'App.tsx').read_text(encoding='utf-8')
    check('undo restores the previous UI', restored is not None and restored_text == original and 'Changed' not in restored_text)
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

    # Leave sandbox clean for the running preview
    workspace.apply_template_app()

    print(NL + 'Result: ' + str(PASS) + ' passed, ' + str(FAIL) + ' failed')
    if FAIL:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

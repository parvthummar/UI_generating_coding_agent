import app.agent as agent_module
from app import tools, validate, workspace
from app.agent import build_user_message, run_turn
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


def write(path, content, description='Test file.', changed=None, seen=None):
    if changed is None:
        changed = set()
    return tools.run_tool(
        'write_file',
        {'path': path, 'content': content, 'description': description},
        changed,
        seen,
    )


def tool_reply(calls, content='ok'):
    raw_calls = []
    parsed = []
    for index, call in enumerate(calls):
        call_id = 'call_' + str(index)
        raw_calls.append({
            'id': call_id,
            'type': 'function',
            'function': {'name': call['name'], 'arguments': '{}'},
        })
        parsed.append({'id': call_id, 'name': call['name'], 'args': call['args']})
    raw = {'role': 'assistant', 'content': content}
    if raw_calls:
        raw['tool_calls'] = raw_calls
    return {'raw_message': raw, 'content': content, 'tool_calls': parsed}


def text_reply(content):
    return {'raw_message': {'role': 'assistant', 'content': content}, 'content': content, 'tool_calls': []}


def scripted_llm(replies, seen_messages):
    def call(messages):
        seen_messages.append(list(messages))
        reply = replies.pop(0)
        yield ('reply', reply)

    return call


def check_descriptions():
    workspace.apply_template_app()
    catalog = workspace.catalog_text(workspace.SANDBOX_SRC, workspace.SANDBOX_DESCRIPTIONS)
    check('starter files have descriptions', 'src/App.tsx' in catalog and 'Starter screen' in catalog)
    check('catalog lists locked files', 'src/main.tsx' in catalog and 'src/index.css' in catalog)
    files = workspace.read_committed_files()
    check('metadata is not a generated source file', 'src/file_descriptions.json' not in files)
    check('metadata file is outside src', not (workspace.SANDBOX_SRC / 'file_descriptions.json').exists())

    workspace.SANDBOX_DESCRIPTIONS.write_text('not json', encoding='utf-8')
    catalog = workspace.catalog_text(workspace.SANDBOX_SRC, workspace.SANDBOX_DESCRIPTIONS)
    check('missing or corrupt descriptions stay readable', 'src/App.tsx' in catalog and '(no description yet)' in catalog)

    workspace.apply_template_app()
    stale = workspace.read_description_map(workspace.SANDBOX_DESCRIPTIONS)
    stale['src/components/Gone.tsx'] = 'This file is gone.'
    stale['../secret.tsx'] = 'should be dropped'
    workspace.write_description_map(workspace.SANDBOX_DESCRIPTIONS, stale)
    catalog = workspace.catalog_text(workspace.SANDBOX_SRC, workspace.SANDBOX_DESCRIPTIONS)
    saved = workspace.read_description_map(workspace.SANDBOX_DESCRIPTIONS)
    check('stale descriptions are removed', 'Gone.tsx' not in catalog and 'src/components/Gone.tsx' not in saved)
    check('unsafe description keys are dropped', '../secret.tsx' not in saved)

    seen = set()
    created = write(
        'components/Keep.tsx',
        'export const keep = 1;\n',
        'File that should survive an edit to another file.',
        set(),
        seen,
    )
    check('new file stores a description', created.startswith('OK:'), created)
    other = write('components/Other.tsx', 'export const other = 1;\n', 'The file we edit.')
    other_seen = set()
    tools.run_tool('read_file', {'path': 'components/Other.tsx'}, set(), other_seen)
    edited = tools.run_tool(
        'edit_file',
        {
            'path': 'components/Other.tsx',
            'old_str': 'export const other = 1;',
            'new_str': 'export const other = 2;',
            'description': 'Edited helper.',
        },
        set(),
        other_seen,
    )
    check('edit can refresh the description', edited.startswith('OK:'), edited)
    staging_desc = workspace.read_description_map(workspace.STAGING_DESCRIPTIONS)
    check('edit keeps the other file', (workspace.STAGING_SRC / 'components' / 'Keep.tsx').exists())
    check('edited description is stored', staging_desc.get('src/components/Other.tsx') == 'Edited helper.')

    delete_seen = set()
    tools.run_tool('read_file', {'path': 'components/Keep.tsx'}, set(), delete_seen)
    deleted = tools.run_tool('delete_file', {'path': 'components/Keep.tsx'}, set(), delete_seen)
    check('delete removes the file', deleted.startswith('OK:'), deleted)
    after_delete = workspace.read_description_map(workspace.STAGING_DESCRIPTIONS)
    check('delete removes the description', 'src/components/Keep.tsx' not in after_delete)
    check('delete does not remove the other description', 'src/components/Other.tsx' in after_delete)

    missing = write('components/NeedDesc.tsx', 'export const n = 1;\n', '')
    check('empty description is rejected', missing.startswith('ERROR:') and 'description' in missing, missing)
    check('rejected write does not create the file', not (workspace.STAGING_SRC / 'components' / 'NeedDesc.tsx').exists())


def check_agent_loop():
    original_llm = agent_module.call_llm
    original_validate = agent_module.validate_staged
    try:
        workspace.apply_template_app()
        before = workspace.read_committed_files()
        replies = [
            tool_reply(
                [
                    {
                        'name': 'write_file',
                        'args': {
                            'path': 'components/Box.tsx',
                            'content': 'export default function Box() { return <div>Box</div>; }\n',
                            'description': 'A small box.',
                        },
                    }
                ]
            ),
            text_reply('Added a box.'),
            text_reply('Fixed the box.'),
        ]
        seen_messages = []
        results = [
            'TypeScript check failed:\nsrc/components/Box.tsx(1,1): error TS1000: synthetic failure',
            '',
        ]

        def validate():
            return results.pop(0)

        agent_module.call_llm = scripted_llm(replies, seen_messages)
        agent_module.validate_staged = validate
        events = ''.join(list(run_turn(Session(), 'Add a box')))
        feedback = ''
        for batch in seen_messages:
            for message in batch:
                if message.get('role') == 'user' and 'synthetic failure' in message.get('content', ''):
                    feedback = message['content']
        committed = workspace.SANDBOX_SRC / 'components' / 'Box.tsx'
        desc = workspace.read_description_map(workspace.SANDBOX_DESCRIPTIONS)
        check('compiler failure is sent back to the model', 'src/components/Box.tsx' in feedback and 'synthetic failure' in feedback)
        check('a later clean check commits', 'files_updated' in events and committed.exists())
        check('committed description matches the write', desc.get('src/components/Box.tsx') == 'A small box.')

        workspace.apply_template_app()
        before = workspace.read_committed_files()
        before_desc = workspace.read_description_map(workspace.SANDBOX_DESCRIPTIONS)
        crash_replies = [
            tool_reply(
                [
                    {
                        'name': 'write_file',
                        'args': {
                            'path': 'components/Boom.tsx',
                            'content': 'export const boom = 1;\n',
                            'description': 'Should not be committed.',
                        },
                    }
                ]
            ),
            text_reply('done'),
            text_reply('done'),
            text_reply('done'),
            text_reply('done'),
        ]
        seen_messages = []

        def crash_validate():
            return 'Runtime smoke test failed:\nThis preview crashed: boom'

        agent_module.call_llm = scripted_llm(crash_replies, seen_messages)
        agent_module.validate_staged = crash_validate
        session = Session()
        events = ''.join(list(run_turn(session, 'Add a crashing widget')))
        check('runtime failure does not commit', 'files_updated' not in events and 'rolled_back' in events)
        check('runtime failure names the reason', '"reason": "runtime"' in events)
        check('three correction attempts are allowed', events.count('fixing_error') == 3)
        check('failed generation leaves the preview', workspace.read_committed_files() == before)
        check(
            'failed generation leaves descriptions',
            workspace.read_description_map(workspace.SANDBOX_DESCRIPTIONS) == before_desc,
        )
        check('rollback clears the staged file', not (workspace.STAGING_SRC / 'components' / 'Boom.tsx').exists())
        check('session records the rollback', session.rollback_pending and session.failed_request == 'Add a crashing widget')
    finally:
        agent_module.call_llm = original_llm
        agent_module.validate_staged = original_validate


def check_validation():
    workspace.apply_template_app()
    marker = 'STAGED_MARKER_12345'
    seen = set()
    tools.run_tool('read_file', {'path': 'App.tsx'}, set(), seen)
    write(
        'App.tsx',
        'export default function App() { return <div className="h-full w-full">' + marker + '</div>; }\n',
        'Staged marker screen.',
        set(),
        seen,
    )
    build_errors = validate.run_production_build()
    check('staged production build succeeds', build_errors == '', build_errors[:400] if build_errors else '')
    dist_text = ''
    dist = workspace.STAGING / 'dist'
    if dist.exists():
        for path in dist.rglob('*'):
            if path.is_file() and path.suffix in ('.js', '.html', '.css'):
                dist_text += path.read_text(encoding='utf-8', errors='ignore')
    sandbox_app = (workspace.SANDBOX_SRC / 'App.tsx').read_text(encoding='utf-8')
    check('build output comes from staging', marker in dist_text and marker not in sandbox_app)

    broken = workspace.STAGING / 'index.html'
    broken.write_text('<html><script type="module" src="/src/missing-entry.tsx"></script></html>', encoding='utf-8')
    build_errors = validate.run_production_build()
    check(
        'build failure includes the missing file',
        build_errors.startswith('Production build failed') and 'missing-entry' in build_errors,
        build_errors[:400] if build_errors else '',
    )

    workspace.apply_template_app()
    clean = validate.validate_staged()
    check('template passes typecheck build and smoke', clean == '', clean[:500] if clean else '')

    seen = set()
    tools.run_tool('read_file', {'path': 'App.tsx'}, set(), seen)
    write(
        'App.tsx',
        'export default function App() {\n  throw new Error("smoke-render-crash");\n  return <div>nope</div>;\n}\n',
        'App that crashes while rendering.',
        set(),
        seen,
    )
    crashed = validate.validate_staged()
    check(
        'render crash fails the smoke test',
        crashed.startswith('Runtime smoke test failed') and 'smoke-render-crash' in crashed,
        crashed[:500] if crashed else '',
    )
    check('smoke failure does not change the committed app', 'smoke-render-crash' not in (workspace.SANDBOX_SRC / 'App.tsx').read_text(encoding='utf-8'))

    workspace.reset_staging_from_sandbox()
    seen = set()
    tools.run_tool('read_file', {'path': 'App.tsx'}, set(), seen)
    write(
        'App.tsx',
        'export default function App() {\n'
        + '  return (\n'
        + '    <div className="h-full w-full">\n'
        + '      <img src="https://example.com/blocked.png" alt="" />\n'
        + '      <p>Mounted</p>\n'
        + '    </div>\n'
        + '  );\n'
        + '}\n',
        'Screen with a blocked remote image.',
        set(),
        seen,
    )
    blocked_image = validate.validate_staged()
    check('blocked remote image is not a smoke failure', blocked_image == '', blocked_image[:500] if blocked_image else '')

    workspace.reset_staging_from_sandbox()
    seen = set()
    tools.run_tool('read_file', {'path': 'App.tsx'}, set(), seen)
    write(
        'App.tsx',
        'import { useEffect } from "react";\n'
        + 'export default function App() {\n'
        + '  useEffect(() => { throw new Error("effect-crash"); }, []);\n'
        + '  return <div>Mounted</div>;\n'
        + '}\n',
        'App that crashes after mount.',
        set(),
        seen,
    )
    effect = validate.validate_staged()
    check(
        'effect crash fails the smoke test',
        effect.startswith('Runtime smoke test failed') and 'effect-crash' in effect,
        effect[:500] if effect else '',
    )


def main():
    workspace.apply_template_app()
    changed = set()

    names = []
    for item in tools.TOOL_DEFINITIONS:
        names.append(item['function']['name'])
    check('tools stay read write edit delete', names == ['read_file', 'write_file', 'edit_file', 'delete_file'])
    write_schema = tools.TOOL_DEFINITIONS[1]['function']
    check(
        'write_file requires a description',
        write_schema['parameters']['required'] == ['path', 'content', 'description'],
    )
    check('prompt and tools agree on the catalog', 'FILE CATALOG' in SYSTEM_PROMPT and 'description' in SYSTEM_PROMPT)
    check('prompt tells the model to read before editing', 'read_file' in SYSTEM_PROMPT and 'edit_file' in SYSTEM_PROMPT)

    # Paths that include the src/ prefix still land inside src/
    result = write('src/components/FromSrc.tsx', 'export const fromSrc = 1;\n', changed=changed)
    from_src = workspace.STAGING_SRC / 'components' / 'FromSrc.tsx'
    nested = workspace.STAGING_SRC / 'src' / 'components' / 'FromSrc.tsx'
    check('src/ prefix stays inside src', result.startswith('OK:') and from_src.exists() and not nested.exists(), result)

    # Creating a file works, and a later edit must have read it first.
    seen = set()
    result = write(
        'components/Hello.tsx',
        'export default function Hello() { return <div>Hi</div>; }\n',
        'Greeting component.',
        changed,
        seen,
    )
    check('creating a file works', result.startswith('OK:'), result)
    hello = workspace.STAGING_SRC / 'components' / 'Hello.tsx'
    unread = tools.run_tool(
        'edit_file',
        {'path': 'components/Hello.tsx', 'old_str': 'Hi', 'new_str': 'Hello'},
        set(),
        set(),
    )
    check('edit without read_file is rejected', unread.startswith('ERROR:') and 'read_file' in unread, unread)
    check('rejected edit does not change the file', 'Hi' in hello.read_text(encoding='utf-8'))
    blank = tools.run_tool(
        'edit_file',
        {'path': 'components/Hello.tsx', 'old_str': 'Hi', 'new_str': 'Hey', 'description': ' '},
        changed,
        seen,
    )
    kept = workspace.read_description_map(workspace.STAGING_DESCRIPTIONS).get('src/components/Hello.tsx')
    check('blank edit description is ignored', blank.startswith('OK:') and 'Hey' in hello.read_text(encoding='utf-8'), blank)
    check('blank edit description keeps the catalog entry', kept == 'Greeting component.')

    # Missing old_str returns an error
    result = tools.run_tool(
        'edit_file',
        {'path': 'components/Hello.tsx', 'old_str': 'this string is not in the file', 'new_str': 'x'},
        changed,
        seen,
    )
    check('missing old_str returns an error', result.startswith('ERROR:') and 'not found' in result, result)

    # Duplicate old_str returns an error and does not modify the file
    dup_seen = set()
    write('components/Dup.tsx', 'const a = 1;\nconst a = 1;\n', 'Duplicate lines.', changed, dup_seen)
    dup_path = workspace.STAGING_SRC / 'components' / 'Dup.tsx'
    before_dup = dup_path.read_text(encoding='utf-8')
    result = tools.run_tool(
        'edit_file',
        {'path': 'components/Dup.tsx', 'old_str': 'const a = 1;', 'new_str': 'const a = 2;'},
        changed,
        dup_seen,
    )
    check('duplicate old_str returns an error', result.startswith('ERROR:') and 'matches' in result, result)
    check('ambiguous edit does not modify the file', dup_path.read_text(encoding='utf-8') == before_dup)
    same = tools.run_tool(
        'edit_file',
        {'path': 'components/Dup.tsx', 'old_str': 'const a = 1;\nconst a = 1;\n', 'new_str': 'const a = 1;\nconst a = 1;\n'},
        changed,
        dup_seen,
    )
    check('identical edit does not count as a change', same.startswith('OK: no change'), same)
    check('identical edit leaves the file untouched', dup_path.read_text(encoding='utf-8') == before_dup)

    # ../x is rejected
    result = write('../x.tsx', 'export {};\n', changed=changed)
    check('../x is rejected', result.startswith('ERROR:') and 'inside src' in result, result)

    # Writing main.tsx is rejected
    result = write('main.tsx', 'export {};\n', changed=changed)
    check('writing main.tsx is rejected', result.startswith('ERROR:') and 'locked' in result, result)

    # Overwriting a long existing file is rejected
    long_text = NL.join(['const n' + str(i) + ' = ' + str(i) + ';' for i in range(70)]) + NL
    long_seen = set()
    write('components/Long.tsx', long_text, 'A long generated file.', changed, long_seen)
    result = write('components/Long.tsx', 'export {};\n', changed=changed, seen=long_seen)
    check(
        'overwriting a long existing file is rejected',
        result.startswith('ERROR:') and 'edit_file' in result,
        result,
    )

    fresh = set()
    first = write(
        'App.tsx',
        'export default function App() { return <div>Nope</div>; }\n',
        'Should not apply yet.',
        set(),
        fresh,
    )
    check('overwrite without a read returns the current text', first.startswith('ERROR:') and 'Current text of App.tsx' in first, first[:180])
    second = write(
        'App.tsx',
        'export default function App() { return <div>Now</div>; }\n',
        'Replaced after the error showed the file.',
        set(),
        fresh,
    )
    check('the next write can use that returned text', second.startswith('OK:'), second)

    # Template compiles clean (reset staging from sandbox first with clean App)
    workspace.apply_template_app()
    errors = validate.run_tsc()
    check('the template compiles clean', errors == '', errors[:300] if errors else '')

    # After writing a type error, the compiler reports an error
    workspace.reset_staging_from_sandbox()
    bad = "const x: number = 'a';\nexport default function App() { return <div>{x}</div>; }\n"
    app_seen = set()
    tools.run_tool('read_file', {'path': 'App.tsx'}, set(), app_seen)
    write('App.tsx', bad, 'App with a type error.', set(), app_seen)
    errors = validate.run_tsc()
    check('compiler reports an error for bad types', errors != '', errors[:300])

    # Commit copies files
    workspace.apply_template_app()
    workspace.reset_staging_from_sandbox()
    write(
        'components/Committed.tsx',
        'export const marker = "committed-ok";\n',
        'Marker used to prove commit copies files.',
    )
    workspace.commit_staging_to_sandbox()
    committed = workspace.SANDBOX_SRC / 'components' / 'Committed.tsx'
    check('commit copies files', committed.exists() and 'committed-ok' in committed.read_text(encoding='utf-8'))

    # Rollback restores
    workspace.reset_staging_from_sandbox()
    write('components/TempOnly.tsx', 'export const temp = 1;\n', 'Temporary staging file.')
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
    check('committed state is explicit', 'COMMITTED PREVIEW' in committed_note and 'FILE CATALOG' in committed_note)
    check('catalog does not dump source', 'min-h-screen' not in committed_note)
    failed_note = build_user_message('hello', True, 'Finance dashboard')
    check('rolled back request is named', 'FAILED and was rolled back' in failed_note and 'Finance dashboard' in failed_note)

    # Undo restores the previous committed source.
    workspace.apply_template_app()
    original = (workspace.SANDBOX_SRC / 'App.tsx').read_text(encoding='utf-8')
    workspace.reset_staging_from_sandbox()
    undo_seen = set()
    tools.run_tool('read_file', {'path': 'App.tsx'}, set(), undo_seen)
    write(
        'App.tsx',
        'export default function App() { return <div>Changed</div>; }\n',
        'Changed screen for undo.',
        set(),
        undo_seen,
    )
    workspace.commit_staging_to_sandbox()
    changed_text = (workspace.SANDBOX_SRC / 'App.tsx').read_text(encoding='utf-8')
    changed_desc = workspace.read_description_map(workspace.SANDBOX_DESCRIPTIONS)
    check('commit saves a snapshot', 'Changed' in changed_text and workspace.snapshot_count() == 1)
    check('commit stores the file description', changed_desc.get('src/App.tsx') == 'Changed screen for undo.')
    restored = workspace.undo_committed()
    restored_text = (workspace.SANDBOX_SRC / 'App.tsx').read_text(encoding='utf-8')
    restored_desc = workspace.read_description_map(workspace.SANDBOX_DESCRIPTIONS)
    check('undo restores the previous UI', restored is not None and restored_text == original and 'Changed' not in restored_text)
    check('undo restores the description', restored_desc.get('src/App.tsx', '').startswith('Starter screen'))
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

    check_descriptions()
    check_agent_loop()
    check_validation()

    # Leave sandbox clean for the running preview
    workspace.apply_template_app()

    print(NL + 'Result: ' + str(PASS) + ' passed, ' + str(FAIL) + ' failed')
    if FAIL:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

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
        same_error = False
        for batch in seen_messages:
            for message in batch:
                if message.get('role') == 'user' and 'same error as before' in message.get('content', ''):
                    same_error = True
        check('repeated identical validation says to try another approach', same_error)
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


def budget_llm(replies, seen_messages):
    def call(messages):
        seen_messages.append(list(messages))
        last = ''
        if messages:
            last = messages[-1].get('content') or ''
        if 'build budget is used' in last:
            yield ('reply', text_reply('Stopping so validation can run.'))
            return
        yield ('reply', replies.pop(0))

    return call


def always_tool_llm(seen_messages):
    def call(messages):
        seen_messages.append(list(messages))
        yield (
            'reply',
            tool_reply(
                [
                    {
                        'name': 'write_file',
                        'args': {
                            'path': 'components/Again.tsx',
                            'content': 'export const again = 1;\n',
                            'description': 'Repeated write while the budget runs out.',
                        },
                    }
                ]
            ),
        )

    return call


def check_diagnostics():
    workspace.apply_template_app()
    seen = set()
    tools.run_tool('read_file', {'path': 'App.tsx'}, set(), seen)
    write(
        'App.tsx',
        "import React from 'react';\nimport * as React from 'react';\nexport default function App() { return <div>Hi</div>; }\n",
        'Page with two React imports.',
        set(),
        seen,
    )
    duplicate = agent_module.diagnostic_context(
        "src/App.tsx(1,8): error TS2300: Duplicate identifier 'React'.\n"
        + "src/App.tsx(2,13): error TS2300: Duplicate identifier 'React'."
    )
    check('duplicate identifier lists both declarations', 'line 1:' in duplicate and 'line 2:' in duplicate and 'Keep one declaration' in duplicate, duplicate[:500])

    write(
        'components/Board.tsx',
        'import { useState } from "react";\n'
        + 'export default function Board() {\n'
        + '  const [todo, setTodo] = useState([]);\n'
        + '  const [todo, setTodo] = useState([]);\n'
        + '  return <div>{todo.length}</div>;\n'
        + '}\n',
        'Board that declares the same state twice.',
    )
    redeclared = agent_module.diagnostic_context(
        "src/components/Board.tsx(3,10): error TS2451: Cannot redeclare block-scoped variable 'todo'."
    )
    check('redeclared state lists both lines', 'line 3:' in redeclared and 'line 4:' in redeclared and 'Delete the extra declaration' in redeclared, redeclared[:500])

    fancy = 'const label = \u201cHello\u201d;\nexport default function App() { return <div>{label}</div>; }\n'
    column = fancy.index('\u201c') + 1
    write('App.tsx', fancy, 'Page with a curly quote.', set(), seen)
    invalid = agent_module.diagnostic_context(
        'src/App.tsx(1,' + str(column) + '): error TS1127: Invalid character.'
    )
    check('invalid character names the code point', 'U+201C' in invalid and 'plain ASCII' in invalid, invalid[:500])

    write(
        'App.tsx',
        'export default function App() {\n  return <div>Hi</div>;\n}\n}\n',
        'Page with an extra closing brace.',
        set(),
        seen,
    )
    broken = agent_module.diagnostic_context(
        'src/App.tsx(4,1): error TS1128: Declaration or statement expected.'
    )
    check('syntax error quotes the breaking line', 'breaks at line 4' in broken and '4:' in broken, broken[:500])


def check_reference_and_budget():
    workspace.apply_template_app()
    write(
        'components/Widget.tsx',
        'export default function Widget() { return <div>Widget</div>; }\n',
        'A widget component.',
    )
    seen = set()
    tools.run_tool('read_file', {'path': 'App.tsx'}, set(), seen)
    write(
        'App.tsx',
        'export default function App() { return <div><Widget /></div>; }\n',
        'Page that uses Widget without importing it.',
        set(),
        seen,
    )
    errors = "sandbox/.staging/src/App.tsx(1,45): error TS2304: Cannot find name 'Widget'."
    hint = agent_module.symbol_context(errors)
    check(
        'undefined component points at the matching file',
        'src/components/Widget.tsx' in hint and 'default function' in hint,
        hint[:400],
    )
    check('correction hint includes an import', "import Widget from './components/Widget'" in hint, hint[:400])
    missing = agent_module.symbol_context("src/App.tsx(1,1): error TS2304: Cannot find name 'MissingPiece'.")
    check('a name with no export says to create the file', 'not exported' in missing and 'MissingPiece' in missing, missing[:300])
    local_name = agent_module.symbol_context("src/App.tsx(2,8): error TS2304: Cannot find name 'toggleUnit'.")
    check(
        'a local name is not treated as a missing component',
        'Do not create a new component file' in local_name and 'export default function toggleUnit' not in local_name,
        local_name[:300],
    )

    original_llm = agent_module.call_llm
    original_validate = agent_module.validate_staged
    original_tsc = agent_module.run_tsc
    try:
        workspace.apply_template_app()
        before = workspace.read_committed_files()
        before_desc = workspace.read_description_map(workspace.SANDBOX_DESCRIPTIONS)
        replies = []
        index = 0
        while index < agent_module.MAX_STEPS:
            replies.append(
                tool_reply(
                    [
                        {
                            'name': 'write_file',
                            'args': {
                                'path': 'components/Piece' + str(index) + '.tsx',
                                'content': 'export const piece' + str(index) + ' = ' + str(index) + ';\n',
                                'description': 'Piece ' + str(index) + '.',
                            },
                        }
                    ]
                )
            )
            index += 1
        seen_messages = []
        agent_module.call_llm = budget_llm(replies, seen_messages)
        agent_module.run_tsc = lambda: ''
        agent_module.validate_staged = lambda: ''
        events = ''.join(list(run_turn(Session(), 'Keep writing until the budget ends')))
        saw_budget = False
        for batch in seen_messages:
            for message in batch:
                if 'build budget is used' in (message.get('content') or ''):
                    saw_budget = True
        check('a full tool budget gets one chance to stop', saw_budget)
        check('stopping after the budget can still commit', 'files_updated' in events)
        check(
            'the finalized project keeps its descriptions',
            workspace.read_description_map(workspace.SANDBOX_DESCRIPTIONS).get('src/components/Piece0.tsx') == 'Piece 0.',
        )

        workspace.apply_template_app()
        before = workspace.read_committed_files()
        before_desc = workspace.read_description_map(workspace.SANDBOX_DESCRIPTIONS)
        seen_messages = []
        agent_module.call_llm = always_tool_llm(seen_messages)
        agent_module.run_tsc = lambda: ''
        agent_module.validate_staged = lambda: (
            "TypeScript check failed:\nsrc/App.tsx(1,1): error TS2304: Cannot find name 'Nope'."
        )
        session = Session()
        events = ''.join(list(run_turn(session, 'Keep calling tools past the budget')))
        check('tool calls after the budget still require a clean check', 'files_updated' not in events and 'rolled_back' in events)
        check('unfinished work leaves the committed source', workspace.read_committed_files() == before)
        check(
            'unfinished work leaves the committed descriptions',
            workspace.read_description_map(workspace.SANDBOX_DESCRIPTIONS) == before_desc,
        )
        check('the session records that rollback', session.rollback_pending)
    finally:
        agent_module.call_llm = original_llm
        agent_module.validate_staged = original_validate
        agent_module.run_tsc = original_tsc


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


def run_behavior(scenario):
    import subprocess

    script = workspace.REPO / 'sandbox' / 'scripts' / 'behave.mjs'
    dist = workspace.STAGING / 'dist'
    result = subprocess.run(
        ['node', str(script), str(dist), scenario],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(workspace.REPO / 'sandbox'),
    )
    return (result.stdout or '') + (result.stderr or '')


def put_app(content, description):
    seen = set()
    tools.run_tool('read_file', {'path': 'App.tsx'}, set(), seen)
    return write('App.tsx', content, description, set(), seen)


def check_behavior():
    workspace.apply_template_app()
    build_errors = validate.run_production_build()
    check('behavior fixture can build the starter', build_errors == '', build_errors[:300] if build_errors else '')
    output = run_behavior('todo')
    check('a screen with no task field is not an interaction pass', 'BEHAVE_INCONCLUSIVE' in output and 'BEHAVE_PASS' not in output, output[:300])
    output = run_behavior('weather')
    check('a screen with no unit control is inconclusive', 'BEHAVE_INCONCLUSIVE' in output and 'BEHAVE_PASS' not in output, output[:300])

    put_app(
        "import { useState } from 'react';\n"
        + 'export default function App() {\n'
        + "  const [items, setItems] = useState(['Wash', 'Cook']);\n"
        + "  const [text, setText] = useState('');\n"
        + '  return (\n'
        + '    <div>\n'
        + '      <input aria-label="Task" value={text} onChange={(event) => setText(event.target.value)} />\n'
        + '      <button onClick={() => { if (text) { setItems(items.concat(text)); setText(""); } }}>Add</button>\n'
        + '      <p>{items.length} left</p>\n'
        + '      <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>\n'
        + '    </div>\n'
        + '  );\n'
        + '}\n',
        'Task list that starts with two items.',
    )
    build_errors = validate.run_production_build()
    check('behavior fixture builds a task list', build_errors == '', build_errors[:300] if build_errors else '')
    output = run_behavior('todo')
    check('adding a task increases the existing remaining count', 'BEHAVE_PASS' in output and 'from 2 to 3' in output, output[:400])

    put_app(
        "import { useState } from 'react';\n"
        + 'export default function App() {\n'
        + "  const [items, setItems] = useState(['Wash']);\n"
        + "  const [text, setText] = useState('');\n"
        + '  return (\n'
        + '    <div>\n'
        + '      <input aria-label="Task" value={text} onChange={(event) => setText(event.target.value)} />\n'
        + '      <button onClick={() => { if (text) { setItems(items.concat(text)); setText(""); } }}>Add</button>\n'
        + '      <p>1 left</p>\n'
        + '      <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>\n'
        + '    </div>\n'
        + '  );\n'
        + '}\n',
        'Task list whose count does not change.',
    )
    build_errors = validate.run_production_build()
    check('stale count fixture builds', build_errors == '', build_errors[:300] if build_errors else '')
    output = run_behavior('todo')
    check('a stale remaining count fails', 'BEHAVE_FAIL' in output and 'instead of increasing by one' in output, output[:400])

    put_app(
        "import { useEffect, useState } from 'react';\n"
        + 'export default function App() {\n'
        + '  const [seconds, setSeconds] = useState(10);\n'
        + '  const [running, setRunning] = useState(false);\n'
        + '  useEffect(() => {\n'
        + '    if (!running) return;\n'
        + '    const id = setInterval(() => setSeconds((value) => Math.max(0, value - 1)), 1000);\n'
        + '    return () => clearInterval(id);\n'
        + '  }, [running]);\n'
        + "  const label = '0:' + String(seconds).padStart(2, '0');\n"
        + '  return (\n'
        + '    <div>\n'
        + '      <p>{label}</p>\n'
        + '      <button onClick={() => setRunning(true)}>Start</button>\n'
        + '      <button onClick={() => setRunning(false)}>Pause</button>\n'
        + '      <button onClick={() => { setRunning(false); setSeconds(10); }}>Reset</button>\n'
        + '    </div>\n'
        + '  );\n'
        + '}\n',
        'A short countdown with start, pause, and reset.',
    )
    build_errors = validate.run_production_build()
    check('timer fixture builds', build_errors == '', build_errors[:300] if build_errors else '')
    output = run_behavior('pomodoro')
    check('countdown advances, pauses, and resets', 'BEHAVE_PASS' in output, output[:400])

    put_app(
        "import { useState } from 'react';\n"
        + 'export default function App() {\n'
        + "  const [cards, setCards] = useState({ todo: ['Paint'], done: ['Ship'] });\n"
        + '  function move() { setCards({ todo: [], done: ["Ship", "Paint"] }); }\n'
        + '  return (\n'
        + '    <div>\n'
        + '      <section><h2>Todo</h2><ul>{cards.todo.map((card) => <li key={card}>{card}<button onClick={move}>Move</button></li>)}</ul></section>\n'
        + '      <section><h2>Done</h2><ul>{cards.done.map((card) => <li key={card}>{card}</li>)}</ul></section>\n'
        + '    </div>\n'
        + '  );\n'
        + '}\n',
        'Two columns with one move button.',
    )
    build_errors = validate.run_production_build()
    check('board fixture builds', build_errors == '', build_errors[:300] if build_errors else '')
    output = run_behavior('kanban')
    check('a card move is detected across columns', 'BEHAVE_PASS' in output and 'another column' in output, output[:400])

    put_app(
        "import { useState } from 'react';\n"
        + 'export default function App() {\n'
        + '  const [moves, setMoves] = useState(0);\n'
        + '  return (\n'
        + '    <div>\n'
        + '      <section><h2>Todo</h2><ul><li>Paint<button onClick={() => setMoves(moves + 1)}>Move</button></li></ul></section>\n'
        + '      <section><h2>Done</h2><ul><li>Ship</li></ul></section>\n'
        + '      <p>Moves: {moves}</p>\n'
        + '    </div>\n'
        + '  );\n'
        + '}\n',
        'A board whose move button does not move the card.',
    )
    build_errors = validate.run_production_build()
    check('static card fixture builds', build_errors == '', build_errors[:300] if build_errors else '')
    output = run_behavior('kanban')
    check('a text change without a column move fails', 'BEHAVE_FAIL' in output and 'same column' in output, output[:400])

    put_app(
        "import { useState } from 'react';\n"
        + 'export default function App() {\n'
        + "  const [unit, setUnit] = useState('C');\n"
        + "  const value = unit === 'C' ? 20 : 68;\n"
        + '  return (\n'
        + '    <div>\n'
        + '      <p>{value}°{unit}</p>\n'
        + "      <button onClick={() => setUnit(unit === 'C' ? 'F' : 'C')}>{unit === 'C' ? '°F' : '°C'}</button>\n"
        + '    </div>\n'
        + '  );\n'
        + '}\n',
        'A temperature display with a unit button.',
    )
    build_errors = validate.run_production_build()
    check('weather fixture builds', build_errors == '', build_errors[:300] if build_errors else '')
    output = run_behavior('weather')
    check('a temperature unit change passes', 'BEHAVE_PASS' in output, output[:400])


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
    check_diagnostics()
    check_agent_loop()
    check_reference_and_budget()
    check_validation()
    check_behavior()

    # Leave sandbox clean for the running preview
    workspace.apply_template_app()

    print(NL + 'Result: ' + str(PASS) + ' passed, ' + str(FAIL) + ' failed')
    if FAIL:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

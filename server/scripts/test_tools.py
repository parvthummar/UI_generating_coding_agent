import subprocess

import app.agent as agent_module
from app import tools, validate, workspace
from app.agent import build_user_message, correction_text, run_turn
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


def write(path, content, description='Test file.', changed=None):
    if changed is None:
        changed = set()
    return tools.run_tool('write_file', {'path': path, 'content': content, 'description': description}, changed)


def edit(path, old_str, new_str, changed=None):
    if changed is None:
        changed = set()
    return tools.run_tool('edit_file', {'path': path, 'old_str': old_str, 'new_str': new_str}, changed)


def component(name, text):
    return 'export default function ' + name + '() {\n  return <div>' + text + '</div>;\n}\n'


def long_component(name, lines):
    body = 'export default function ' + name + '() {\n  return (\n    <ul>\n'
    for i in range(lines):
        body += '      <li>Row ' + str(i) + '</li>\n'
    return body + '    </ul>\n  );\n}\n'


def commit_files(files):
    # Put files straight into the committed preview, as if an earlier turn had made them.
    workspace.apply_template_app()
    for rel in files:
        target = workspace.SANDBOX_SRC / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(files[rel], encoding='utf-8')
    workspace.reset_staging_from_sandbox()


def tool_reply(calls, content=''):
    raw_calls = []
    parsed = []
    for index, call in enumerate(calls):
        call_id = 'call_' + str(index)
        raw_calls.append({'id': call_id, 'type': 'function', 'function': {'name': call['name'], 'arguments': '{}'}})
        parsed.append({'id': call_id, 'name': call['name'], 'args': call['args']})
    raw = {'role': 'assistant', 'content': content, 'tool_calls': raw_calls}
    return {'raw_message': raw, 'content': content, 'tool_calls': parsed}


def text_reply(content):
    return {'raw_message': {'role': 'assistant', 'content': content}, 'content': content, 'tool_calls': []}


def write_call(path, content):
    return {'name': 'write_file', 'args': {'path': path, 'content': content, 'description': 'Test.'}}


def scripted_llm(replies, seen_messages):
    def call(messages):
        seen_messages.append(messages)
        yield ('reply', replies.pop(0))

    return call


def events_of(stream):
    return ''.join(list(stream))


class Patch:
    # Swap the model and the full validation for a scripted run, then put them back.
    def __init__(self, llm, validate_fn=None):
        self.llm = llm
        self.validate_fn = validate_fn

    def __enter__(self):
        self.old_llm = agent_module.call_llm
        self.old_validate = agent_module.validate_staged
        agent_module.call_llm = self.llm
        if self.validate_fn is not None:
            agent_module.validate_staged = self.validate_fn
        return self

    def __exit__(self, *args):
        agent_module.call_llm = self.old_llm
        agent_module.validate_staged = self.old_validate


def check_tools():
    workspace.apply_template_app()
    names = []
    for item in tools.TOOL_DEFINITIONS:
        names.append(item['function']['name'])
    check('tools stay read write edit delete', names == ['read_file', 'write_file', 'edit_file', 'delete_file'])

    changed = set()
    result = write('src/components/FromSrc.tsx', 'export const fromSrc = 1;\n', changed=changed)
    from_src = workspace.STAGING_SRC / 'components' / 'FromSrc.tsx'
    nested = workspace.STAGING_SRC / 'src' / 'components' / 'FromSrc.tsx'
    check('src/ prefix stays inside src', result.startswith('OK:') and from_src.exists() and not nested.exists(), result)
    check('a write is recorded as a change', 'components/FromSrc.tsx' in changed)

    result = edit('App.tsx', '<div className="min-h-screen bg-white" />', "import X from './X';\n<X />")
    check('editing the blank starter is refused', result.startswith('ERROR:') and 'write_file' in result, result)
    result = write('App.tsx', component('App', 'New first screen'))
    check('the starter App can be replaced without reading it first', result.startswith('OK:'), result)

    result = write('components/Hello.tsx', component('Hello', 'Hi'))
    check('creating a file works', result.startswith('OK:'), result)
    result = edit('components/Hello.tsx', 'Hi', 'Hello')
    check('edit replaces one exact match', result.startswith('OK:') and 'Hello' in (workspace.STAGING_SRC / 'components' / 'Hello.tsx').read_text(encoding='utf-8'), result)

    result = edit('components/Hello.tsx', 'this string is not in the file', 'x')
    check('missing old_str returns an error with the current text', result.startswith('ERROR:') and 'not found' in result and 'Current text' in result, result[:200])

    write('components/Dup.tsx', 'const a = 1;\nconst a = 1;\n')
    dup_path = workspace.STAGING_SRC / 'components' / 'Dup.tsx'
    before_dup = dup_path.read_text(encoding='utf-8')
    result = edit('components/Dup.tsx', 'const a = 1;', 'const a = 2;')
    check('duplicate old_str returns an error', result.startswith('ERROR:') and 'matches 2 places' in result, result[:200])
    check('ambiguous edit does not modify the file', dup_path.read_text(encoding='utf-8') == before_dup)
    same = set()
    result = edit('components/Dup.tsx', 'const a = 1;\nconst a = 1;\n', 'const a = 1;\nconst a = 1;\n', same)
    check('an edit that changes nothing is reported as an error', result.startswith('ERROR:') and 'nothing changed' in result and len(same) == 0, result[:200])

    write('components/Indent.tsx', 'export default function Indent() {\n    return (\n        <p>Old</p>\n    );\n}\n')
    result = edit('components/Indent.tsx', '  return (\n    <p>Old</p>', 'return (\n  <p>New</p>')
    indent_text = (workspace.STAGING_SRC / 'components' / 'Indent.tsx').read_text(encoding='utf-8')
    check('an edit with different indentation still applies once', result.startswith('OK:') and '<p>New</p>' in indent_text and 'Old' not in indent_text, result[:200])
    check('the indentation fallback keeps the rest of the file', indent_text.startswith('export default function Indent() {\n') and indent_text.endswith('    );\n}\n'), indent_text)
    result = edit('components/Indent.tsx', 'not here', 'x')
    check('a failed edit on a new file offers write_file', 'replace the whole file with write_file' in result, result[:200])

    crlf = workspace.STAGING_SRC / 'components' / 'Crlf.tsx'
    crlf.write_bytes(b'const a = 1;\r\nconst b = 2;\r\n')
    result = edit('components/Crlf.tsx', 'const a = 1;\nconst b = 2;', 'const a = 3;\nconst b = 4;')
    check('Windows and Unix line endings match the same text', result.startswith('OK:'), result[:200])

    result = write('../x.tsx', 'export {};\n')
    check('../x is rejected', result.startswith('ERROR:') and 'inside src' in result, result)
    result = write('C:/Windows/evil.tsx', 'export {};\n')
    check('an absolute path is rejected', result.startswith('ERROR:'), result)
    result = write('main.tsx', 'export {};\n')
    check('writing main.tsx is rejected', result.startswith('ERROR:') and 'locked' in result, result)
    result = write('components/style.css', 'body {}\n')
    check('non-TypeScript files are rejected', result.startswith('ERROR:'), result)
    result = tools.run_tool('delete_file', {'path': 'App.tsx'}, set())
    check('App.tsx cannot be deleted', result.startswith('ERROR:'), result)
    result = tools.run_tool('write_file', {'_bad_json': True}, set())
    check('bad JSON arguments return an error', result.startswith('ERROR:') and 'JSON' in result, result)

    result = tools.run_tool('write_file', {'path': 'components/NoDesc.tsx', 'content': component('NoDesc', 'x')}, set())
    check('a missing description is not a tool error', result.startswith('OK:'), result)


def check_rewrite_rule():
    # A file the model creates in this turn may be rewritten while it fixes it.
    workspace.apply_template_app()
    write('components/Fresh.tsx', long_component('Fresh', 80))
    result = write('components/Fresh.tsx', long_component('Fresh', 90))
    check('a long file created in this turn can be rewritten', result.startswith('OK:'), result[:200])

    # A long file the user already sees must be edited, not rewritten.
    commit_files({'components/Big.tsx': long_component('Big', 70)})
    result = write('components/Big.tsx', component('Big', 'gone'))
    check('a long committed file cannot be rewritten', result.startswith('ERROR:') and 'edit_file' in result, result[:200])
    check('the refusal shows the current text', 'Current text of components/Big.tsx' in result)
    result = edit('components/Big.tsx', '<li>Row 3</li>', '<li>Row three</li>')
    check('a long committed file can still be edited', result.startswith('OK:'), result[:200])
    result = edit('components/Big.tsx', 'not here', 'x')
    check('a failed edit on a long committed file does not offer write_file', result.startswith('ERROR:') and 'write_file' not in result.split('\n')[0], result[:200])

    commit_files({'components/Small.tsx': component('Small', 'tiny')})
    result = write('components/Small.tsx', component('Small', 'replaced'))
    check('a short committed file can be rewritten', result.startswith('OK:'), result[:200])


def check_workspace():
    workspace.apply_template_app()
    errors = validate.run_tsc()
    check('the template compiles clean', errors == '', errors[:300])

    write('App.tsx', "const x: number = 'a';\nexport default function App() { return <div>{x}</div>; }\n")
    errors = validate.run_tsc()
    check('compiler reports an error for bad types', errors != '', errors[:300])
    check('compiler paths match the paths the model uses', 'src/App.tsx' in errors and '.staging' not in errors, errors[:300])

    workspace.apply_template_app()
    write('components/Committed.tsx', 'export const marker = "committed-ok";\n', 'Marker.')
    workspace.commit_staging_to_sandbox()
    committed = workspace.SANDBOX_SRC / 'components' / 'Committed.tsx'
    check('commit copies files', committed.exists() and 'committed-ok' in committed.read_text(encoding='utf-8'))
    desc = workspace.read_description_map(workspace.SANDBOX_DESCRIPTIONS)
    check('commit keeps the file description', desc.get('src/components/Committed.tsx') == 'Marker.')

    workspace.reset_staging_from_sandbox()
    write('components/TempOnly.tsx', 'export const temp = 1;\n')
    staging_temp = workspace.STAGING_SRC / 'components' / 'TempOnly.tsx'
    workspace.reset_staging_from_sandbox()
    check('rollback drops staged files', not staging_temp.exists())
    check('rollback leaves committed files', committed.exists() and not (workspace.SANDBOX_SRC / 'components' / 'TempOnly.tsx').exists())

    workspace.reset_staging_from_sandbox()
    tools.run_tool('delete_file', {'path': 'components/Committed.tsx'}, set())
    workspace.commit_staging_to_sandbox()
    check('commit removes deleted files', not committed.exists())

    workspace.apply_template_app()
    original = (workspace.SANDBOX_SRC / 'App.tsx').read_text(encoding='utf-8')
    write('App.tsx', component('App', 'Changed'))
    workspace.commit_staging_to_sandbox()
    check('commit saves a snapshot', workspace.snapshot_count() == 1)
    restored = workspace.undo_committed()
    restored_text = (workspace.SANDBOX_SRC / 'App.tsx').read_text(encoding='utf-8')
    check('undo restores the previous UI', restored is not None and restored_text == original)
    check('undo with no snapshot returns nothing', workspace.undo_committed() is None)


def check_context():
    workspace.apply_template_app()
    check('the message says when the project is the blank starter', 'blank starter' in build_user_message('build a form'))

    commit_files({
        'App.tsx': "import Header from './components/Header';\nexport default function App() { return <Header />; }\n",
        'components/Header.tsx': component('Header', 'Brand header'),
    })
    message = build_user_message('make it green')
    check('the user message carries the committed source', 'Brand header' in message and '=== src/components/Header.tsx ===' in message)
    check('the user message keeps the request', message.endswith('User request: make it green'))
    check('locked files are not pasted', 'createRoot' not in message)
    check('a built project is not called the starter', 'blank starter' not in message)

    big = {}
    for i in range(8):
        big['components/Big' + str(i) + '.tsx'] = '// ' + ('x' * 5000) + '\n' + component('Big' + str(i), 'big')
    commit_files(big)
    message = build_user_message('hello')
    check('a large project lists the files that do not fit', 'not shown because the project is large' in message and 'read_file' in message)
    check('the snapshot stays under the cap', len(message) < agent_module.SNAPSHOT_CHARS + 2000, str(len(message)))

    check('prompt names the tools', 'write_file' in SYSTEM_PROMPT and 'edit_file' in SYSTEM_PROMPT)
    check('prompt fixes one import style', 'export default function' in SYSTEM_PROMPT)
    check('prompt lists the installed packages', 'recharts' in SYSTEM_PROMPT and 'lucide-react' in SYSTEM_PROMPT)

    workspace.apply_template_app()
    write('App.tsx', 'export default function App() {\n  return <div>{missing}</div>;\n}\n')
    errors = validate.run_tsc()
    text = correction_text('TypeScript check failed:\n' + errors, False)
    check('correction quotes the failing line', 'src/App.tsx line 2:' in text and '{missing}' in text, text[:400])
    check('correction includes the current file', 'Current text of src/App.tsx' in text)
    again = correction_text('TypeScript check failed:\n' + errors, True)
    check('a repeated error asks for another approach', 'try a different approach' in again)

    workspace.apply_template_app()
    write('components/Testimonials.tsx', component('Testimonials', 'Quotes'))
    write('App.tsx', 'export default function App() {\n  return <Testimonials />;\n}\n')
    errors = validate.run_tsc()
    text = correction_text(errors, False)
    check('a missing component import gets the exact import line', "import Testimonials from './components/Testimonials';" in text, text[:400])


def check_agent_loop():
    # Interim compiler errors while the UI is half built must not use correction rounds.
    workspace.apply_template_app()
    replies = [
        tool_reply([write_call('App.tsx', "import Hero from './components/Hero';\nexport default function App() { return <Hero />; }\n")]),
        tool_reply([write_call('components/Hero.tsx', component('Hero', 'Welcome'))]),
        text_reply('Built a hero.'),
    ]
    seen = []
    with Patch(scripted_llm(replies, seen), lambda: validate.run_tsc()):
        events = events_of(run_turn(Session(), 'Build a hero'))
    first_tool = ''
    for message in seen[-1]:
        if message.get('role') == 'tool':
            first_tool = message['content']
            break
    check('interim errors are shown to the model', 'Hero' in first_tool and 'Type check after this step' in first_tool, first_tool[:300])
    check('interim errors do not use a correction round', 'fixing_error' not in events, events[:300])
    check('the finished UI commits', 'files_updated' in events and (workspace.SANDBOX_SRC / 'components' / 'Hero.tsx').exists())
    check('the commit event names the changed files', '"changed": ["src/App.tsx", "src/components/Hero.tsx"]' in events, events[-400:])

    # A model that keeps repeating a broken state gets the current file text, still without a correction round.
    workspace.apply_template_app()
    broken = 'export default function App() {\n  return <Hero />;\n}\n'
    other = 'export default function App() {\n  return <div><Hero /></div>;\n}\n'
    replies = [
        tool_reply([write_call('components/Hero.tsx', component('Hero', 'Hi')), write_call('App.tsx', broken)]),
        tool_reply([write_call('App.tsx', other)]),
        tool_reply([write_call('App.tsx', broken)]),
        tool_reply([write_call('App.tsx', "import Hero from './components/Hero';\n" + broken)]),
        text_reply('Fixed the import.'),
    ]
    seen = []
    with Patch(scripted_llm(replies, seen), lambda: validate.run_tsc()):
        events = events_of(run_turn(Session(), 'Build a hero'))
    tool_texts = []
    for message in seen[-1]:
        if message.get('role') == 'tool':
            tool_texts.append(message['content'])
    check('a first interim error does not paste whole files', 'Current text of' not in tool_texts[1], tool_texts[1][-300:])
    check('an error seen earlier in the turn brings the current file text', 'Current text of src/App.tsx' in tool_texts[3] and 'same error as before' in tool_texts[3], tool_texts[3][-300:])
    check('interim errors carry the import hint', "import Hero from './components/Hero';" in tool_texts[1])
    check('a repeated interim error still does not use a correction round', 'fixing_error' not in events and 'files_updated' in events)

    # Every tool call in one step runs, none are silently dropped.
    workspace.apply_template_app()
    calls = []
    imports = ''
    tags = ''
    for i in range(7):
        name = 'Part' + str(i)
        calls.append(write_call('components/' + name + '.tsx', component(name, name)))
        imports += 'import ' + name + " from './components/" + name + "';\n"
        tags += '<' + name + ' />'
    calls.append(write_call('App.tsx', imports + 'export default function App() { return <div>' + tags + '</div>; }\n'))
    seen = []
    with Patch(scripted_llm([tool_reply(calls), text_reply('Built seven parts.')], seen), lambda: validate.run_tsc()):
        events = events_of(run_turn(Session(), 'Build seven parts'))
    tool_messages = 0
    for message in seen[-1]:
        if message.get('role') == 'tool':
            tool_messages += 1
    check('all 8 tool calls in one step run', events.count('"name": "write_file"') == 8 and tool_messages == 8, str(tool_messages))
    check('a many-file step commits', 'files_updated' in events and (workspace.SANDBOX_SRC / 'components' / 'Part6.tsx').exists())

    # A follow-up edit leaves unrelated files byte-for-byte unchanged.
    commit_files({
        'App.tsx': "import Header from './components/Header';\nimport Footer from './components/Footer';\n"
        + 'export default function App() { return <div><Header /><Footer /></div>; }\n',
        'components/Header.tsx': component('Header', 'Brand'),
        'components/Footer.tsx': component('Footer', 'Copyright'),
    })
    before = workspace.read_committed_files()
    replies = [
        tool_reply([{'name': 'edit_file', 'args': {'path': 'components/Header.tsx', 'old_str': 'Brand', 'new_str': 'Green brand'}}]),
        text_reply('Made the header green.'),
    ]
    session = Session()
    with Patch(scripted_llm(replies, []), lambda: ''):
        events = events_of(run_turn(session, 'Make the header green'))
    after = workspace.read_committed_files()
    check('a follow-up edit commits', 'files_updated' in events and 'Green brand' in after['src/components/Header.tsx'])
    check(
        'unrelated files are unchanged after a follow-up',
        after['src/App.tsx'] == before['src/App.tsx'] and after['src/components/Footer.tsx'] == before['src/components/Footer.tsx'],
    )
    check('history records the request and the changed file', 'components/Header.tsx' in session.history[-1]['content'])

    # Three failed checks roll back, and the next request still runs normally.
    commit_files({'components/Keep.tsx': component('Keep', 'kept')})
    before = workspace.read_committed_files()
    before_desc = workspace.read_description_map(workspace.SANDBOX_DESCRIPTIONS)
    replies = [tool_reply([write_call('components/Boom.tsx', 'export const boom = 1;\n')])]
    for i in range(4):
        replies.append(text_reply('done'))
    seen = []
    session = Session()
    with Patch(scripted_llm(replies, seen), lambda: 'Runtime smoke test failed:\nThis preview crashed: boom'):
        events = events_of(run_turn(session, 'Add a crashing widget'))
    check('a runtime failure does not commit', 'files_updated' not in events and '"reason": "runtime"' in events)
    check('three correction rounds are allowed', events.count('fixing_error') == 3, str(events.count('fixing_error')))
    repeated = False
    for message in seen[-1]:
        if message.get('role') == 'user' and 'try a different approach' in (message.get('content') or ''):
            repeated = True
    check('the same failure twice asks for another approach', repeated)
    check('a failed turn leaves the preview unchanged', workspace.read_committed_files() == before)
    check('a failed turn leaves the descriptions unchanged', workspace.read_description_map(workspace.SANDBOX_DESCRIPTIONS) == before_desc)
    check('rollback clears the staged file', not (workspace.STAGING_SRC / 'components' / 'Boom.tsx').exists())
    check('history says the turn failed', 'FAILED and rolled back' in session.history[-1]['content'])
    seen = []
    with Patch(scripted_llm([text_reply('The last change was rolled back, nothing to edit yet.')], seen), lambda: ''):
        events = events_of(run_turn(session, 'Make it blue'))
    check('a request after a rollback still reaches the model', 'assistant_message' in events and len(seen) == 1)
    check('the model sees the failed turn in its history', 'FAILED and rolled back' in str(seen[0]))

    # Running out of steps with a finished project still gets one full check.
    workspace.apply_template_app()
    replies = []
    for i in range(agent_module.MAX_STEPS):
        replies.append(tool_reply([write_call('components/Piece' + str(i) + '.tsx', 'export const piece' + str(i) + ' = 1;\n')]))
    with Patch(scripted_llm(replies, []), lambda: ''):
        events = events_of(run_turn(Session(), 'Keep writing'))
    check('a clean project at the step limit commits', 'files_updated' in events)

    workspace.apply_template_app()
    before = workspace.read_committed_files()
    replies = []
    for i in range(agent_module.MAX_STEPS):
        replies.append(tool_reply([write_call('components/Piece' + str(i) + '.tsx', 'export const piece' + str(i) + ' = 1;\n')]))
    with Patch(scripted_llm(replies, []), lambda: "TypeScript check failed:\nsrc/App.tsx(1,1): error TS2304: Cannot find name 'Nope'."):
        events = events_of(run_turn(Session(), 'Keep writing'))
    check('a broken project at the step limit rolls back', 'files_updated' not in events and workspace.read_committed_files() == before)

    # A plain question changes nothing and commits nothing.
    workspace.apply_template_app()
    with Patch(scripted_llm([text_reply('It is a blank page.')], []), lambda: 'should not run'):
        events = events_of(run_turn(Session(), 'What is on screen?'))
    check('a turn without edits does not validate or commit', 'files_updated' not in events and 'validating' not in events)


def check_validation():
    workspace.apply_template_app()
    marker = 'STAGED_MARKER_12345'
    write('App.tsx', 'export default function App() { return <div className="h-full w-full">' + marker + '</div>; }\n')
    build_errors = validate.run_production_build()
    check('staged production build succeeds', build_errors == '', build_errors[:400])
    dist_text = ''
    dist = workspace.STAGING / 'dist'
    if dist.exists():
        for path in dist.rglob('*'):
            if path.is_file() and path.suffix in ('.js', '.html', '.css'):
                dist_text += path.read_text(encoding='utf-8', errors='ignore')
    sandbox_app = (workspace.SANDBOX_SRC / 'App.tsx').read_text(encoding='utf-8')
    check('build output comes from staging', marker in dist_text and marker not in sandbox_app)

    workspace.apply_template_app()
    clean = validate.validate_staged()
    check('template passes typecheck build and smoke', clean == '', clean[:500])

    write('App.tsx', "import { format } from 'date-fns';\nexport default function App() { return <div>{format(new Date(), 'P')}</div>; }\n")
    missing = validate.validate_staged()
    check('an uninstalled package fails the check', missing.startswith('TypeScript check failed') and 'date-fns' in missing, missing[:300])

    workspace.reset_staging_from_sandbox()
    write('App.tsx', 'export default function App() {\n  throw new Error("smoke-render-crash");\n  return <div>nope</div>;\n}\n')
    crashed = validate.validate_staged()
    check('render crash fails the smoke test', crashed.startswith('Runtime smoke test failed') and 'smoke-render-crash' in crashed, crashed[:500])
    check('smoke failure does not change the committed app', 'smoke-render-crash' not in (workspace.SANDBOX_SRC / 'App.tsx').read_text(encoding='utf-8'))

    workspace.reset_staging_from_sandbox()
    write(
        'App.tsx',
        'import { useEffect } from "react";\n'
        + 'export default function App() {\n'
        + '  useEffect(() => { throw new Error("effect-crash"); }, []);\n'
        + '  return <div>Mounted</div>;\n'
        + '}\n',
    )
    effect = validate.validate_staged()
    check('effect crash fails the smoke test', effect.startswith('Runtime smoke test failed') and 'effect-crash' in effect, effect[:500])

    workspace.reset_staging_from_sandbox()
    write(
        'App.tsx',
        'export default function App() {\n  return (\n    <div>\n      <img src="https://example.com/blocked.png" alt="" />\n'
        + '      <p>Mounted</p>\n    </div>\n  );\n}\n',
    )
    blocked = validate.validate_staged()
    check('blocked remote image is not a smoke failure', blocked == '', blocked[:500])


def run_behavior(scenario):
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


def behavior_case(name, app_text, scenario, expected, detail_text=''):
    workspace.reset_staging_from_sandbox()
    write('App.tsx', app_text)
    build_errors = validate.run_production_build()
    if build_errors:
        check(name, False, build_errors[:300])
        return
    output = run_behavior(scenario)
    check(name, expected in output and (detail_text == '' or detail_text in output), output[:300])


def check_behavior():
    workspace.apply_template_app()
    build_errors = validate.run_production_build()
    check('behavior fixture can build the starter', build_errors == '', build_errors[:300])
    check('a screen with no task field is inconclusive', 'BEHAVE_INCONCLUSIVE' in run_behavior('todo'))

    todo = (
        "import { useState } from 'react';\n"
        + 'export default function App() {\n'
        + "  const [items, setItems] = useState(['Wash', 'Cook']);\n"
        + "  const [text, setText] = useState('');\n"
        + '  return (\n'
        + '    <div>\n'
        + '      <input aria-label="Task" value={text} onChange={(event) => setText(event.target.value)} />\n'
        + '      <button onClick={() => { if (text) { setItems(items.concat(text)); setText(""); } }}>Add</button>\n'
        + '      <p>COUNT left</p>\n'
        + '      <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>\n'
        + '    </div>\n'
        + '  );\n'
        + '}\n'
    )
    behavior_case('adding a task increases the remaining count', todo.replace('COUNT', '{items.length}'), 'todo', 'BEHAVE_PASS', 'from 2 to 3')
    behavior_case('a stale remaining count fails', todo.replace('COUNT', '2'), 'todo', 'BEHAVE_FAIL')
    div_todo = todo.replace('COUNT', '{items.length}').replace('<ul>', '<div>').replace('</ul>', '</div>').replace('<li key', '<div key').replace('</li>', '</div>')
    behavior_case('tasks rendered as divs still count as added', div_todo, 'todo', 'BEHAVE_PASS', 'from 2 to 3')
    no_add = todo.replace('COUNT', '{items.length}').replace('setItems(items.concat(text)); ', '')
    behavior_case('a task that never appears fails', no_add, 'todo', 'BEHAVE_FAIL', 'did not appear')

    timer = (
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
        + '}\n'
    )
    behavior_case('countdown advances, pauses, and resets', timer, 'pomodoro', 'BEHAVE_PASS')
    toggle = timer.replace(
        '      <button onClick={() => setRunning(true)}>Start</button>\n      <button onClick={() => setRunning(false)}>Pause</button>\n',
        "      <button onClick={() => setRunning(!running)}>{running ? 'Pause' : 'Start'}</button>\n",
    )
    behavior_case('a single start and pause toggle passes', toggle, 'pomodoro', 'BEHAVE_PASS')
    frozen = timer.replace('setSeconds((value) => Math.max(0, value - 1))', 'setSeconds((value) => value)')
    behavior_case('a timer that never counts down fails', frozen, 'pomodoro', 'BEHAVE_FAIL', 'did not advance')

    board = (
        "import { useState } from 'react';\n"
        + 'export default function App() {\n'
        + "  const [cards, setCards] = useState({ todo: ['Paint'], done: ['Ship'] });\n"
        + '  function move() { setCards({ todo: [], done: ["Ship", "Paint"] }); }\n'
        + '  return (\n'
        + '    <div className="flex gap-8">\n'
        + '      <section className="w-48"><h2>Todo</h2><ul>{cards.todo.map((card) => <li key={card}>{card}<button onClick={move}>Move</button></li>)}</ul></section>\n'
        + '      <section className="w-48"><h2>Done</h2><ul>{cards.done.map((card) => <li key={card}>{card}</li>)}</ul></section>\n'
        + '    </div>\n'
        + '  );\n'
        + '}\n'
    )
    behavior_case('a card move is detected across columns', board, 'kanban', 'BEHAVE_PASS', 'another column')
    div_board = board.replace('<ul>', '<div>').replace('</ul>', '</div>').replace('<li key={card}>{card}', '<div key={card}><h3>{card}</h3>').replace('</li>', '</div>')
    behavior_case('cards rendered as divs with heading titles are detected', div_board, 'kanban', 'BEHAVE_PASS', 'another column')
    two_way = (
        "import { useState } from 'react';\n"
        + 'export default function App() {\n'
        + "  const [cols, setCols] = useState([['Paint'], ['Ship']]);\n"
        + '  function shift(card: string, from: number, by: number) {\n'
        + '    const to = Math.min(1, Math.max(0, from + by));\n'
        + '    if (to === from) return;\n'
        + '    const next = cols.map((col) => col.filter((c) => c !== card));\n'
        + '    next[to] = next[to].concat(card);\n'
        + '    setCols(next);\n'
        + '  }\n'
        + '  return (\n'
        + '    <div className="flex gap-8">\n'
        + '      {cols.map((col, i) => (\n'
        + '        <div key={i} className="w-48"><h2>{i === 0 ? "Todo" : "Done"}</h2>\n'
        + '          {col.map((card) => (\n'
        + '            <div key={card}><h3>{card}</h3>\n'
        + '              <button onClick={() => shift(card, i, -1)}>Move Left</button>\n'
        + '              <button onClick={() => shift(card, i, 1)}>Move Right</button>\n'
        + '            </div>\n'
        + '          ))}\n'
        + '        </div>\n'
        + '      ))}\n'
        + '    </div>\n'
        + '  );\n'
        + '}\n'
    )
    behavior_case('a left move on the first column does not hide a working right move', two_way, 'kanban', 'BEHAVE_PASS', 'another column')
    stuck_board = board.replace('function move() { setCards({ todo: [], done: ["Ship", "Paint"] }); }', 'function move() {}')
    behavior_case('a move button that does nothing fails', stuck_board, 'kanban', 'BEHAVE_FAIL', 'same column')

    weather = (
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
        + '}\n'
    )
    behavior_case('a temperature unit change passes', weather, 'weather', 'BEHAVE_PASS')


def check_isolation_config():
    vite_config = (workspace.REPO / 'sandbox' / 'vite.config.ts').read_text(encoding='utf-8')
    check(
        'preview CSP blocks remote network',
        "connect-src 'self'" in vite_config and 'frame-ancestors http://localhost:5173' in vite_config and 'https:' not in vite_config,
    )
    check('preview cannot serve the parent repo', 'allow: [sandboxRoot]' in vite_config and 'envDir: sandboxRoot' in vite_config)
    client_app = (workspace.REPO / 'client' / 'src' / 'App.tsx').read_text(encoding='utf-8')
    check('iframe stays sandboxed', 'sandbox="allow-scripts allow-same-origin allow-modals"' in client_app)
    check('runtime crash can be sent for repair', 'Ask the agent to fix this' in client_app)
    sandbox_main = (workspace.REPO / 'sandbox' / 'src' / 'main.tsx').read_text(encoding='utf-8')
    check('runtime errors are reported to the host', "type: 'SANDBOX_RUNTIME_ERROR'" in sandbox_main)


def main():
    check_tools()
    check_rewrite_rule()
    check_workspace()
    check_context()
    check_agent_loop()
    check_validation()
    check_behavior()
    check_isolation_config()

    # Leave the sandbox clean for the running preview.
    workspace.apply_template_app()

    print(NL + 'Result: ' + str(PASS) + ' passed, ' + str(FAIL) + ' failed')
    if FAIL:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

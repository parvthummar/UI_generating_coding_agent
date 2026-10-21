import difflib
import json
import subprocess
import time
from pathlib import Path

from app.agent import run_turn
from app.sessions import Session
from app.validate import run_production_build
from app.workspace import STAGING, apply_template_app, read_committed_files

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / 'eval' / 'results.md'
PAUSE_SECONDS = 5
BEHAVIOR = {
    'F2': 'todo',
    '5': 'pomodoro',
    '7': 'kanban',
    '8': 'weather',
}

CASES = [
    {
        'id': '1',
        'kind': 'Form',
        'prompt': 'Contact form with name, email and message, validation, and a success message',
        'followups': [
            {
                'id': 'F4',
                'kind': 'Follow-up on 1',
                'prompt': 'Make the message field optional',
            },
        ],
    },
    {
        'id': '2',
        'kind': 'Dashboard',
        'prompt': 'Finance dashboard with summary cards, a bar chart of spending, and a transactions table with mock data',
        'followups': [
            {
                'id': 'F1',
                'kind': 'Follow-up on 2',
                'prompt': 'Add a dark mode toggle in the header',
            },
        ],
    },
    {
        'id': '3',
        'kind': 'Landing page',
        'prompt': 'Landing page for a fictional coffee brand with hero, features, pricing and footer',
        'followups': [
            {
                'id': 'F3',
                'kind': 'Follow-up on 3',
                'prompt': 'Change the main color to green and add a testimonials section',
            },
        ],
    },
    {
        'id': '4',
        'kind': 'Small app',
        'prompt': 'Todo app with add, complete, delete and filter',
        'followups': [
            {
                'id': 'F2',
                'kind': 'Follow-up on 4',
                'prompt': 'Show how many tasks are left',
            },
        ],
    },
    {
        'id': '5',
        'kind': 'Small app',
        'prompt': 'Pomodoro timer with start, pause and reset',
        'followups': [],
    },
    {
        'id': '6',
        'kind': 'Form',
        'prompt': 'Login and sign-up screen with a toggle between them',
        'followups': [],
    },
    {
        'id': '7',
        'kind': 'Small app',
        'prompt': 'Kanban board with 3 columns and buttons to move cards',
        'followups': [],
    },
    {
        'id': '8',
        'kind': 'Dashboard',
        'prompt': 'Weather card UI with mock data and a Celsius or Fahrenheit toggle',
        'followups': [],
    },
    {
        'id': 'E1',
        'kind': 'Self-correction',
        'prompt': 'Activity feed with 5 mock events that uses the date-fns library to show relative dates',
        'followups': [],
    },
]


def parse_event(raw):
    name = ''
    data = {}
    for line in raw.strip().split('\n'):
        if line.startswith('event: '):
            name = line[7:]
        elif line.startswith('data: '):
            data = json.loads(line[6:])
    return name, data


def changed_files(before, after):
    names = set(before) | set(after)
    changed = []
    for name in sorted(names):
        if before.get(name) != after.get(name):
            changed.append(name)
    return changed


def kept_share(before, after):
    # Share of the previous lines that are still there after the turn. A full rewrite scores low.
    total = 0
    kept = 0
    for name in before:
        old_lines = before[name].splitlines()
        new_lines = after.get(name, '').splitlines()
        total += len(old_lines)
        matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
        for block in matcher.get_matching_blocks():
            kept += block.size
    if total == 0:
        return ''
    return str(round(100.0 * kept / total)) + '%'


def run_prompt(session, prompt, phase):
    before = read_committed_files()
    started = time.perf_counter()
    model_calls = 0
    fix_attempts = 0
    tool_errors = 0
    committed = False
    failed = False
    reason = ''
    error_message = ''
    for raw in run_turn(session, prompt):
        name, data = parse_event(raw)
        if name == 'status' and data.get('phase') == 'thinking':
            model_calls += 1
        if name == 'status' and data.get('phase') == 'fixing_error':
            fix_attempts += 1
            if data.get('reason'):
                reason = data.get('reason')
        if name == 'tool_call' and not data.get('ok'):
            tool_errors += 1
        if name == 'files_updated':
            committed = True
            reason = ''
        if name == 'error':
            failed = True
            reason = data.get('reason') or data.get('code') or 'error'
            error_message = data.get('message') or ''
    seconds = round(time.perf_counter() - started, 1)
    after = read_committed_files()
    files = changed_files(before, after)
    kept = ''
    if phase == 'follow-up':
        kept = kept_share(before, after)
    if committed and not failed:
        result = 'committed'
    elif failed:
        result = 'rolled_back'
    else:
        result = 'no_change'
    return {
        'phase': phase,
        'prompt': prompt,
        'build_passed': result == 'committed',
        'result': result,
        'reason': reason,
        'model_calls': model_calls,
        'fix_attempts': fix_attempts,
        'tool_errors': tool_errors,
        'seconds': seconds,
        'files_changed': files,
        'kept': kept,
        'detail': error_message[:500],
        'render': 'pass' if result == 'committed' else ('fail' if reason == 'runtime' else 'not_reached'),
        'interaction': 'not_run',
        'interaction_detail': '',
    }


def skipped_followup(follow, initial_id):
    return {
        'id': follow['id'],
        'phase': 'follow-up',
        'prompt': follow['prompt'],
        'build_passed': False,
        'result': 'skipped',
        'reason': 'initial_failed',
        'model_calls': 0,
        'fix_attempts': 0,
        'tool_errors': 0,
        'seconds': 0,
        'files_changed': [],
        'kept': '',
        'render': 'not_run',
        'interaction': 'not_run',
        'interaction_detail': '',
        'detail': (
            'Not executed. Initial prompt '
            + initial_id
            + ' did not commit, so this row is not an iterative-edit result.'
        ),
    }


def run_behavior(scenario):
    errors = run_production_build()
    if errors:
        return 'not_checked', 'The staged build failed before the interaction check.'
    script = REPO / 'sandbox' / 'scripts' / 'behave.mjs'
    dist = STAGING / 'dist'
    try:
        result = subprocess.run(
            ['node', str(script), str(dist), scenario],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(REPO / 'sandbox'),
        )
    except subprocess.TimeoutExpired:
        return 'not_checked', 'The interaction check timed out.'
    output = ((result.stdout or '') + '\n' + (result.stderr or '')).strip()
    reason = ''
    for line in output.splitlines():
        if line.startswith('BEHAVE_') or line.strip() == '':
            continue
        reason = line.strip()
        break
    if 'BEHAVE_PASS' in output:
        return 'pass', reason
    if 'BEHAVE_INCONCLUSIVE' in output:
        return 'inconclusive', reason
    if 'BEHAVE_FAIL' in output:
        return 'fail', reason or 'The interaction check failed.'
    return 'not_checked', output[:300]


def attach_behavior(row):
    scenario = BEHAVIOR.get(row.get('id'))
    if not scenario or not row.get('build_passed'):
        return
    kind, detail = run_behavior(scenario)
    row['interaction'] = kind
    row['interaction_detail'] = detail
    print('INTERACTION ' + row['id'] + ' ' + kind + ' ' + detail)


def cell(value):
    return str(value).replace('|', '/')


def summary_lines(rows):
    initial = []
    follow = []
    for row in rows:
        if row['phase'] == 'initial':
            initial.append(row)
        elif row['phase'] == 'follow-up':
            follow.append(row)
    executed = []
    skipped = []
    for row in follow:
        if row['result'] == 'skipped':
            skipped.append(row)
        else:
            executed.append(row)
    initial_ok = 0
    for row in initial:
        if row['build_passed']:
            initial_ok += 1
    follow_ok = 0
    for row in executed:
        if row['build_passed']:
            follow_ok += 1
    commits = 0
    render_pass = 0
    interaction = {'pass': 0, 'fail': 0, 'inconclusive': 0, 'not_run': 0, 'not_checked': 0}
    step_limit = 0
    corrections_exhausted = 0
    for row in rows:
        if row['build_passed']:
            commits += 1
        if row.get('render') == 'pass':
            render_pass += 1
        kind = row.get('interaction') or 'not_run'
        if kind not in interaction:
            kind = 'not_run'
        interaction[kind] += 1
        if row.get('reason') == 'step_limit':
            step_limit += 1
        if row.get('reason') == 'compiler' and row.get('fix_attempts') == 3 and not row['build_passed']:
            corrections_exhausted += 1
    return [
        'Initial generation: ' + str(initial_ok) + ' of ' + str(len(initial)) + ' committed.',
        'Follow-ups executed against a committed UI: '
        + str(follow_ok)
        + ' of '
        + str(len(executed))
        + ' committed.',
        'Follow-ups skipped because the initial generation did not commit: '
        + str(len(skipped))
        + '. These are not iterative-edit successes and are not in the follow-up denominator.',
        'Rows with a clean commit: '
        + str(commits)
        + ' of '
        + str(len(rows))
        + '. That total mixes new UIs and follow-ups. Use the two rates above.',
        'Initial-render validation passed for '
        + str(render_pass)
        + ' of '
        + str(len(rows))
        + ' rows. A commit requires the staged smoke test, so a committed row passed the initial render. A rolled-back row did not.',
        'Functional interaction checks, only on the todo follow-up, Pomodoro, Kanban, and weather prompts when those UIs committed: '
        + str(interaction['pass'])
        + ' passed, '
        + str(interaction['fail'])
        + ' failed, '
        + str(interaction['inconclusive'])
        + ' inconclusive, '
        + str(interaction['not_checked'])
        + ' not checked, '
        + str(interaction['not_run'])
        + ' not run. A mount is not an interaction pass.',
        'Step-limit rollbacks: '
        + str(step_limit)
        + '. Compiler correction exhausted after 3 attempts: '
        + str(corrections_exhausted)
        + '.',
    ]


def write_results(rows):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        '# Eval results',
        '',
        'Fresh run of `python -m scripts.eval` from the `server` folder.',
        'Each initial prompt starts from the starter project. A follow-up runs only after that prompt commits, in the same session, against the committed UI.',
        'Passing the type check is not enough to commit: the staged project must also pass the production build and the browser smoke test.',
        '',
    ]
    lines.extend(summary_lines(rows))
    lines.extend(
        [
            '',
            '| # | Phase | Prompt | Result | Reason | Render | Interaction | Model calls | Fix attempts | Tool errors | Seconds | Files changed | Previous lines kept |',
            '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |',
        ]
    )
    for row in rows:
        files = ', '.join(row['files_changed']) if row['files_changed'] else ''
        lines.append(
            '| '
            + row['id']
            + ' | '
            + row['phase']
            + ' | '
            + cell(row['prompt'])
            + ' | '
            + row['result']
            + ' | '
            + cell(row['reason'])
            + ' | '
            + cell(row.get('render') or '')
            + ' | '
            + cell(row.get('interaction') or '')
            + ' | '
            + str(row['model_calls'])
            + ' | '
            + str(row['fix_attempts'])
            + ' | '
            + str(row['tool_errors'])
            + ' | '
            + str(row['seconds'])
            + ' | '
            + cell(files)
            + ' | '
            + cell(row.get('kept') or '')
            + ' |'
        )
    lines.append('')
    for row in rows:
        if row.get('detail'):
            lines.append(row['id'] + ': ' + row['detail'])
        if row.get('interaction_detail'):
            lines.append(row['id'] + ' interaction: ' + row['interaction_detail'])
    lines.append('')
    OUT.write_text('\n'.join(lines), encoding='utf-8')
    print('Wrote ' + str(OUT))
    for line in summary_lines(rows):
        print(line)


def main():
    rows = []
    for case in CASES:
        print('RESET before ' + case['id'])
        apply_template_app()
        session = Session()
        print('RUN ' + case['id'] + ': ' + case['prompt'])
        row = run_prompt(session, case['prompt'], 'initial')
        row['id'] = case['id']
        attach_behavior(row)
        rows.append(row)
        print(row)
        time.sleep(PAUSE_SECONDS)
        if row['build_passed']:
            for follow in case['followups']:
                print('RUN ' + follow['id'] + ': ' + follow['prompt'])
                follow_row = run_prompt(session, follow['prompt'], 'follow-up')
                follow_row['id'] = follow['id']
                attach_behavior(follow_row)
                rows.append(follow_row)
                print(follow_row)
                time.sleep(PAUSE_SECONDS)
        else:
            for follow in case['followups']:
                print('SKIP ' + follow['id'] + ' because ' + case['id'] + ' did not commit')
                rows.append(skipped_followup(follow, case['id']))
    order = ['1', 'F4', '2', 'F1', '3', 'F3', '4', 'F2', '5', '6', '7', '8', 'E1']
    by_id = {}
    for row in rows:
        by_id[row['id']] = row
    ordered = []
    for name in order:
        ordered.append(by_id[name])
    write_results(ordered)


if __name__ == '__main__':
    main()

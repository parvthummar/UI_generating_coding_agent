import json
import time
from pathlib import Path

from app.agent import run_turn
from app.sessions import Session
from app.workspace import apply_template_app, read_committed_files

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / 'eval' / 'results.md'
PAUSE_SECONDS = 5

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
    files = changed_files(before, read_committed_files())
    if failed and reason == 'followup_blocked':
        result = 'blocked'
    elif committed and not failed:
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
        'detail': error_message[:500],
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
        'detail': (
            'Not executed. Initial prompt '
            + initial_id
            + ' did not commit, so this row is not an iterative-edit result. '
            + 'The server would refuse the follow-up before any model call.'
        ),
    }


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
    for row in rows:
        if row['build_passed']:
            commits += 1
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
            '| # | Phase | Prompt | Result | Reason | Model calls | Fix attempts | Tool errors | Seconds | Files changed |',
            '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |',
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
            + str(row['model_calls'])
            + ' | '
            + str(row['fix_attempts'])
            + ' | '
            + str(row['tool_errors'])
            + ' | '
            + str(row['seconds'])
            + ' | '
            + cell(files)
            + ' |'
        )
    lines.append('')
    for row in rows:
        if row.get('detail'):
            lines.append(row['id'] + ': ' + row['detail'])
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
        rows.append(row)
        print(row)
        time.sleep(PAUSE_SECONDS)
        if row['build_passed']:
            for follow in case['followups']:
                print('RUN ' + follow['id'] + ': ' + follow['prompt'])
                follow_row = run_prompt(session, follow['prompt'], 'follow-up')
                follow_row['id'] = follow['id']
                rows.append(follow_row)
                print(follow_row)
                time.sleep(PAUSE_SECONDS)
        else:
            for follow in case['followups']:
                print('SKIP ' + follow['id'] + ' because ' + case['id'] + ' did not commit')
                rows.append(skipped_followup(follow, case['id']))
    order = ['1', 'F4', '2', 'F1', '3', 'F3', '4', 'F2', '5', '6', '7', '8']
    by_id = {}
    for row in rows:
        by_id[row['id']] = row
    ordered = []
    for name in order:
        ordered.append(by_id[name])
    write_results(ordered)


if __name__ == '__main__':
    main()

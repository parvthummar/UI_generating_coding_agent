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


def run_prompt(session, prompt):
    before = read_committed_files()
    started = time.perf_counter()
    model_calls = 0
    fix_attempts = 0
    committed = False
    failed = False
    for raw in run_turn(session, prompt):
        name, data = parse_event(raw)
        if name == 'status' and data.get('phase') == 'thinking':
            model_calls += 1
        if name == 'status' and data.get('phase') == 'fixing_error':
            fix_attempts += 1
        if name == 'files_updated':
            committed = True
        if name == 'error':
            failed = True
    seconds = round(time.perf_counter() - started, 1)
    files = changed_files(before, read_committed_files())
    return {
        'prompt': prompt,
        'build_passed': committed and not failed,
        'model_calls': model_calls,
        'fix_attempts': fix_attempts,
        'seconds': seconds,
        'files_changed': files,
    }


def cell(value):
    return str(value).replace('|', '/')


def write_results(rows):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    passed = 0
    for row in rows:
        if row['build_passed']:
            passed += 1
    lines = [
        '# Eval results',
        '',
        'Real run of `python -m scripts.eval` from the `server` folder.',
        str(passed) + ' of ' + str(len(rows)) + ' prompts ended in a clean commit.',
        '',
        '| # | Prompt | Build passed | Model calls | Fix attempts | Seconds | Files changed |',
        '| --- | --- | --- | --- | --- | --- | --- |',
    ]
    for row in rows:
        files = ', '.join(row['files_changed']) if row['files_changed'] else ''
        lines.append(
            '| '
            + row['id']
            + ' | '
            + cell(row['prompt'])
            + ' | '
            + ('yes' if row['build_passed'] else 'no')
            + ' | '
            + str(row['model_calls'])
            + ' | '
            + str(row['fix_attempts'])
            + ' | '
            + str(row['seconds'])
            + ' | '
            + cell(files)
            + ' |'
        )
    lines.append('')
    OUT.write_text('\n'.join(lines), encoding='utf-8')
    print('Wrote ' + str(OUT))


def main():
    rows = []
    for case in CASES:
        print('RESET before ' + case['id'])
        apply_template_app()
        session = Session()
        print('RUN ' + case['id'] + ': ' + case['prompt'])
        row = run_prompt(session, case['prompt'])
        row['id'] = case['id']
        rows.append(row)
        print(row)
        time.sleep(PAUSE_SECONDS)
        for follow in case['followups']:
            print('RUN ' + follow['id'] + ': ' + follow['prompt'])
            follow_row = run_prompt(session, follow['prompt'])
            follow_row['id'] = follow['id']
            rows.append(follow_row)
            print(follow_row)
            time.sleep(PAUSE_SECONDS)
    order = ['1', '2', '3', '4', '5', '6', '7', '8', 'F1', 'F2', 'F3', 'F4']
    by_id = {}
    for row in rows:
        by_id[row['id']] = row
    ordered = []
    for name in order:
        ordered.append(by_id[name])
    write_results(ordered)


if __name__ == '__main__':
    main()

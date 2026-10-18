import json
import sys

from app.agent import run_turn
from app.sessions import Session
from app.workspace import apply_template_app


def print_event(raw):
    # Pretty-print SSE blocks for the terminal.
    name = ''
    data = ''
    for line in raw.strip().split('\n'):
        if line.startswith('event: '):
            name = line[7:]
        elif line.startswith('data: '):
            data = line[6:]
    if not name:
        print(raw)
        return
    try:
        payload = json.loads(data) if data else {}
    except ValueError:
        payload = data
    print('[' + name + '] ' + json.dumps(payload, ensure_ascii=False))


def main():
    session = Session()
    print('UI Agent CLI. Type a request, or /reset, or /quit.')
    while True:
        try:
            line = input('You> ').strip()
        except EOFError:
            print()
            break
        if line == '':
            continue
        if line in ('/quit', '/exit'):
            break
        if line == '/reset':
            apply_template_app()
            session.clear()
            print('[status] session and sandbox reset')
            continue
        for event in run_turn(session, line):
            print_event(event)


if __name__ == '__main__':
    main()

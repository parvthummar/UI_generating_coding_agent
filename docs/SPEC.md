# UI Agent: PRD and Technical Spec

Written for the local coding agent that will build the project, and for Parv, who reviews each step. Target: a working prototype in one day, using the OpenAI API and keeping token use low.

## 0. How to use this document

1. Save this file as `docs/SPEC.md` in the repo. Put the short rule list from section 12 in `AGENTS.md` at the repo root.
2. The agent builds one increment at a time (section 10). After each one it runs that increment's check, commits, tags, and stops.
3. Parv reviews, then tells the agent to start the next increment. If an increment goes wrong, roll back to the last tag (section 11).
4. The assignment requirements in section 2 are the source of truth. If anything in this document conflicts with them, the assignment wins.

## 1. What we are building

UI Agent is a web app with a chat on the left and a live preview on the right. The user types a request such as 'build a personal finance dashboard with a spending chart'. An AI agent writes React code, the TypeScript compiler checks it, and the result appears in the preview and in a read-only code view. The user then sends follow-ups such as 'add a dark mode toggle', and the agent edits only the files and lines that need to change.

It helps to picture three levels:

- Level 1, create: the agent writes a few files and the preview shows the UI.
- Level 2, edit: the agent sees the current files and makes small search-and-replace edits instead of rewriting.
- Level 3, self-heal: if the compiler finds an error, the error text goes back to the AI model and it fixes its own mistake. A change reaches the preview only when the compiler is happy.

The point of the assignment is to show how the agent is designed, not how many features exist. So every choice below favors the smallest thing that works and can be explained.

## 2. Requirements traceability

Every row is an assignment requirement. Nothing outside this table is required.

| Assignment requirement | How we meet it | How we verify |
| --- | --- | --- |
| Chat interface with follow-ups in one conversation | Chat panel, one server-side session, history kept in memory | Send two prompts in a row, the second builds on the first |
| Live preview next to the chat, updates after every change | Vite sandbox on port 5174 inside an iframe, refreshed on commit | Preview changes after each successful turn |
| Code view in sync with the preview | Read-only file tree and viewer, filled from the same commit event | Shown file text equals the file on disk |
| Follow-ups do not throw away the UI | `edit_file` tool, `write_file` refuses to overwrite long existing files, current files are shown to the model | Eval: files not related to the follow-up are byte-for-byte unchanged |
| Context across turns | Stored history of requests and answers, plus a fresh file snapshot every turn | 'Make it green' works without naming a file |
| Variety of UI | Eval set of 8 prompts: forms, dashboards, landing pages, small apps | Eval table in the README |
| A real agent loop, the LLM chooses its tools | Model picks among 4 tools, our code only enforces limits | Terminal log of one turn shows model-chosen tool calls |
| Self-correction on build errors | Compiler errors are returned to the model, up to 3 fix attempts | Demo prompt that forces an error (section 13) |
| Generated code should run without errors | Commit only after a clean compile, plus runtime error report from the preview | Preview never shows a broken state after a failed turn |
| Isolation | Preview on a different origin, trusted files locked, path jail, rollback | Try writing `main.tsx` or `../x`, it is rejected |
| Secrets in environment variables | `.env` is gitignored, `.env.example` is committed | `git check-ignore .env` prints `.env` |
| Runs locally with a few commands | 4 commands in the README, one of them activates a Python virtual environment | Fresh clone test |
| Clean repo, commits show how it was built | One branch per increment, tags, readable messages | `git log --oneline` tells the story |
| Deliverables | Repo, README, demo recording | Checklist in section 16 |

## 3. Scope

In scope: split-screen workspace, one agent loop with 4 tools, targeted edits, compiler check before commit, automatic fix attempts, rollback on failure, live status streaming, runtime error button, a small eval, README, demo.

Out of scope: login, multiple users, databases, installing npm packages at runtime, several cooperating AI agents, undo history, deployment to the cloud, syntax highlighting, mobile layout. If the agent is tempted to add any of these, it must not.

## 4. Terms

| Term | Meaning |
| --- | --- |
| PRD | Product Requirements Document: says what to build and why |
| LLM | Large Language Model: the AI that writes the code |
| Tool calling | Instead of plain text, the model replies 'call function X with these arguments'. Our server runs it and sends the result back |
| Agent loop (ReAct, Reason and Act) | Repeat: model decides, server runs tools, results go back to the model, until the model stops asking for tools |
| tsc | The TypeScript compiler. `tsc --noEmit` only checks the code and prints errors, it produces no files |
| Vite | A development server for React projects. It refreshes the page when files change (HMR, Hot Module Replacement) |
| Origin | Protocol plus host plus port. `localhost:5173` and `localhost:5174` are different origins, so the browser stops them from reading each other's data |
| iframe | A web page embedded inside another page |
| SSE | Server-Sent Events: the server pushes lines of text to the browser over one open HTTP connection |
| CORS | Cross-Origin Resource Sharing: the browser rule that decides which origins may call a server |
| RPM, TPM | Requests per minute and tokens per minute, the two main OpenAI rate limits. A token is roughly three quarters of a word |
| HTTP 429 | The status code that means 'rate limit hit, slow down' |
| Staging, committed | Staging is the working copy the agent edits. Committed is the copy the user sees in the preview |
| FastAPI | A Python web framework. You write plain functions and it turns them into HTTP routes |
| ASGI, uvicorn | ASGI (Asynchronous Server Gateway Interface) is the standard way a Python web app and a web server talk to each other. uvicorn is the ASGI server program that runs our FastAPI app |
| Virtual environment (venv) | A private folder of Python packages for one project, so installs do not touch the rest of your computer |
| Generator | A Python function that uses `yield` to hand back values one at a time. We use one to stream events to the browser as they happen |

## 4b. Tech stack and why

| Layer | Choice | Why |
| --- | --- | --- |
| Host app | React 18, TypeScript, Vite, Tailwind CSS 4 | Fast, typed, free, what the assignment asks for |
| Server | Python 3.11+, FastAPI, uvicorn | Plain functions, easy streaming with a generator, and the language you already use for agent loops |
| LLM access | `openai` Python package | Official OpenAI SDK. Base URL, model and API key come from `.env` |
| Config | `python-dotenv` | Reads the `.env` file at the repo root |
| LLM provider | OpenAI (`gpt-4o-mini` by default) | Tool calling supported. Change `LLM_MODEL` in `.env` if you want a different OpenAI model |
| Node | Node 20+ | Still needed for the client, the preview project and the compiler check, even though the server is Python |
| Preview | A separate Vite project in `sandbox/` on port 5174 | Real hot reload, no paid cloud sandbox, different origin gives isolation |
| Allowed packages for generated UI | react, react-dom, lucide-react, recharts, framer-motion, clsx, tailwind-merge, tailwindcss | Pre-installed so the model never needs `npm install`. Most build errors from models are made-up imports, a fixed list prevents them |
| Validator | `tsc --noEmit` on `sandbox/.staging/`, started by the Python server through `node` | Deterministic, catches syntax errors, missing imports and wrong props |
| Dev runner | `concurrently` (an npm package) at the repo root | One command starts the client, the sandbox and the server |

Pin exact versions in each `package.json` and in `server/requirements.txt` after the first install.

## 5. Architecture

```
Browser: http://localhost:5173   (client/)
 +------------------+   +--------------------------+
 | Chat + tool pills |   | Preview (iframe) or      |
 | + status          |   | Code viewer + file list  |
 +---------+--------+   +------------+-------------+
           | fetch POST /api/chat       | iframe src = http://localhost:5174
           | (streamed response)        | postMessage: runtime errors go back up
           v                            v
Server: http://localhost:8000  (server/)      Sandbox: http://localhost:5174  (sandbox/)
 +--------------------------------+  commit  +------------------------------+
 | FastAPI routes (Python)        |  copies  | Vite + React + Tailwind      |
 | Agent loop: 1 LLM, 4 tools     +--------->| src/main.tsx   (trusted)     |
 | Path-jailed tools              |  files   | src/App.tsx    (agent)       |
 | tsc check via node on          |          | src/components (agent)       |
 |   sandbox/.staging/            |          |                              |
 +---------------+----------------+          +------------------------------+
                 | HTTPS, OpenAI-compatible
                 v
        OpenAI API
```

One turn, step by step:

```
user message
  1. copy sandbox/src to sandbox/.staging/src
  2. build the prompt: rules + file snapshot + history + the request
  3. LOOP, at most 8 model calls
       model asked for tools?
         yes: run tools on staging, run tsc, if errors send them back (at most 3 times)
         no : model is done, final tsc check, clean means COMMIT, errors mean send back
  4. COMMIT: copy staging/src to sandbox/src, preview refreshes, send files_updated
  5. out of steps or fix attempts: ROLLBACK (drop staging), tell the user honestly
```

Strictly speaking this is a loop with a feedback edge, not a DAG. Router, editor, debugger and reviewer are not separate AI agents. They are modes of the same loop, driven by the system prompt and the tool results. Say this in the README.

## 6. Repository layout

```
ui-agent/
  AGENTS.md  README.md  .env.example  .gitignore  package.json
  docs/SPEC.md
  client/                 host app (React)
  server/                 Python backend
    requirements.txt      fastapi, uvicorn, openai, python-dotenv
    app/                  main.py agent.py llm.py tools.py workspace.py validate.py prompts.py sessions.py
    scripts/              test_tools.py cli.py eval.py reset.py
    template/src/App.tsx  starter file copied in by reset
  sandbox/                trusted preview project
    .staging/             created at runtime, gitignored
  eval/results.md
```

Gitignore these: `node_modules`, `.venv`, `__pycache__`, `.env`, `sandbox/.staging`, `sandbox/src/App.tsx`, `sandbox/src/components/`. The generated files are runtime state, not source. The `reset` script copies `server/template/src/App.tsx` into the sandbox and staging folders. Put an empty `__init__.py` in `app/` and in `scripts/` so Python treats them as packages.

Root `package.json` has two scripts. `setup` runs `npm install` in the root, client and sandbox, then `pip install -r server/requirements.txt`, then the reset script (`cd server && python -m scripts.reset`). `dev` uses `concurrently` to start the client, the sandbox and the server (`python -m uvicorn app.main:app --app-dir server --port 8000`). Activate the Python virtual environment before running either one, otherwise `pip` and `python` point at the wrong place.

`.env.example`:

```
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=put-your-key-here
```

## 7. The sandbox project

It is a normal Vite React TypeScript project with Tailwind and the allowed packages. Settings that matter:

- `vite.config.ts`: port 5174 with `strictPort: true`, `server.hmr.overlay: false` so Vite's red error screen never appears (errors are shown by our own error boundary instead), and `server.watch.ignored: ['**/.staging/**']` so writes in the staging folder never disturb the preview.
- `tsconfig.json`: one plain file, not the split `references` layout that Vite's template creates, so the staging config can extend it. Settings: `jsx: react-jsx`, `strict: false`, `skipLibCheck: true`, `noEmit: true`. Loose strictness keeps the compiler from nagging about small typing details, which wastes the model's limited retries.
- `src/index.css` contains the Tailwind import and is trusted.
- `src/main.tsx` is trusted. It wraps `App` in an error boundary and reports crashes to the host page. This is the one place where a class component is needed, because React error boundaries cannot be written as functions.

```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

const HOST_ORIGIN = 'http://localhost:5173';

function report(message: string, stack?: string) {
  window.parent.postMessage({ type: 'SANDBOX_RUNTIME_ERROR', message, stack }, HOST_ORIGIN);
}

window.addEventListener('error', (e) => report(e.message, e.error ? e.error.stack : undefined));
window.addEventListener('unhandledrejection', (e) => report(String(e.reason)));

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error: error };
  }
  componentDidCatch(error: Error) {
    report(error.message, error.stack);
  }
  render() {
    if (this.state.error) {
      return <div className='p-6 text-red-700'>This preview crashed: {this.state.error.message}</div>;
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>
);
```

The host embeds it with `<iframe src='http://localhost:5174' sandbox='allow-scripts allow-same-origin'>`. Be accurate about why this is isolated: the protection comes from the different port, which makes it a different origin. The sandbox attribute alone, with `allow-same-origin`, would not be enough on the same origin. The server also allows CORS only from `http://localhost:5173`, so code in the preview cannot call the server API. Generated code can still reach the public internet, which is listed as a known limit.

## 8. Server design

### 8.1 Who may change which file

| Files | Rule |
| --- | --- |
| `package.json`, `vite.config.ts`, `tsconfig.json`, `index.html`, `src/main.tsx`, `src/index.css` | Locked. Only humans change them |
| `src/App.tsx` | Agent may edit, may not delete |
| `src/components/**` | Agent may create, edit, delete. Only `.tsx` and `.ts` files, at most 25 files, at most 40 KB each |

### 8.2 Path jail

Every tool resolves the path the model gave and rejects anything outside `sandbox/.staging/src`. Plain version:

```python
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]   # this file is server/app/tools.py
ROOT = (REPO / 'sandbox' / '.staging' / 'src').resolve()
LOCKED = ['main.tsx', 'index.css']


def safe_path(user_path):
    full = (ROOT / user_path).resolve()
    if ROOT not in full.parents:
        raise ValueError('Path must be inside src/')
    if full.name in LOCKED and full.parent == ROOT:
        raise ValueError(full.name + ' is locked and cannot be changed')
    if full.suffix not in ('.ts', '.tsx'):
        raise ValueError('Only .ts and .tsx files are allowed')
    return full
```

The check `ROOT in full.parents` means the final path must sit somewhere below `src/`. `resolve()` removes any `..` first. A sibling folder such as `src-evil` fails the check, and so does an absolute path like `/etc/passwd`, because joining an absolute path throws away `ROOT`. `run_tool` catches the `ValueError` and returns it to the model as an `ERROR:` string.

### 8.3 The four tools

Tools return plain strings. Failures start with `ERROR:` and say how to fix the call, so the model can retry.

| Tool | Arguments | Behavior |
| --- | --- | --- |
| `read_file` | `path` | Returns the file text. Useful after the model has edited a file and wants the new state |
| `write_file` | `path`, `content` | Creates a file. If the file exists and has more than 60 lines, returns `ERROR: use edit_file for this file`. This protects the 'targeted edits' rule |
| `edit_file` | `path`, `old_str`, `new_str` | Replaces `old_str` with `new_str`. Zero matches: `ERROR: old_str not found, use read_file to see the current text`. More than one match: `ERROR: old_str matches N places, include more surrounding lines`. Treat Windows and Unix line endings as the same before matching |
| `delete_file` | `path` | Deletes a file. Refuses `App.tsx` |

A tool definition in the OpenAI format looks like this. Write the other three the same way, with short plain descriptions.

```python
TOOL_DEFINITIONS = [
    {
        'type': 'function',
        'function': {
            'name': 'edit_file',
            'description': 'Replace old_str with new_str in an existing file. old_str must match exactly once.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {'type': 'string'},
                    'old_str': {'type': 'string'},
                    'new_str': {'type': 'string'},
                },
                'required': ['path', 'old_str', 'new_str'],
            },
        },
    },
]
```

For example, `edit_file` can be this small (the other tools follow the same shape):

```python
def edit_file(path, old_str, new_str):
    full = safe_path(path)
    if not full.exists():
        return 'ERROR: file does not exist, use write_file to create it'
    text = full.read_text(encoding='utf-8').replace('\r\n', '\n')
    count = text.count(old_str)
    if count == 0:
        return 'ERROR: old_str not found, use read_file to see the current text'
    if count > 1:
        return 'ERROR: old_str matches ' + str(count) + ' places, include more surrounding lines'
    full.write_text(text.replace(old_str, new_str), encoding='utf-8')
    return 'OK: edited ' + path
```

If the model sends arguments that are not valid JSON, return `ERROR: arguments were not valid JSON` instead of crashing.

There is no `run_checks` tool. The server runs the compiler automatically, so the model cannot forget to, and one fewer tool means fewer wrong tool choices and fewer API calls.

### 8.4 The compiler check

Run the compiler directly from the sandbox's `node_modules`, not through `npx`, which is slower to start.

```python
import subprocess


def run_tsc():
    cmd = [
        'node',
        'sandbox/node_modules/typescript/bin/tsc',
        '--noEmit',
        '-p',
        'sandbox/.staging/tsconfig.json',
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=REPO)
    except subprocess.TimeoutExpired:
        return 'Compiler did not finish within 60 seconds'
    output = (result.stdout + result.stderr).strip()
    return output[:4000]   # an empty string means no errors
```

`sandbox/.staging/` holds only `src/` and a tiny `tsconfig.json` that extends the sandbox's own one, shown next. Because the folder lives inside `sandbox/`, the compiler finds `react` and the other packages by looking in parent folders. That means no second `npm install` and no folder shortcut. Create the folder and the file once in the `reset` script.

```json
{
  "extends": "../tsconfig.json",
  "include": ["src"]
}
```

Do not promise a compile time. Expect a few seconds. `skipLibCheck` helps.

### 8.5 The agent loop

The model chooses tools. The code below only enforces limits and the commit gate. `run_turn` is a generator: each `yield` hands one event to the browser as it happens. Keep it this small and readable.

```python
import json

MAX_STEPS = 8
MAX_FIX_RETRIES = 3
NL = '\n'


def sse(name, data):
    return 'event: ' + name + NL + 'data: ' + json.dumps(data) + NL + NL


def run_turn(session, user_text):
    reset_staging_from_sandbox()
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    messages = messages + session.history
    messages.append({'role': 'user', 'content': build_user_message(user_text)})
    changed = set()
    checked_clean = False
    fix_retries = 0
    last_errors = ''

    for step in range(1, MAX_STEPS + 1):
        yield sse('status', {'phase': 'thinking', 'step': step})
        reply = call_llm(messages)
        messages.append(reply['raw_message'])

        if len(reply['tool_calls']) == 0:
            # The model says it is finished. This is the commit gate.
            if len(changed) == 0:
                session.add_turn(user_text, reply['content'], [])
                yield sse('assistant_message', {'text': reply['content']})
                return
            if not checked_clean:
                yield sse('status', {'phase': 'validating'})
                errors = run_tsc()
                if errors != '':
                    fix_retries += 1
                    if fix_retries > MAX_FIX_RETRIES:
                        break
                    text = 'The compiler reports errors:' + NL + errors + NL + 'Please fix them.'
                    messages.append({'role': 'user', 'content': text})
                    last_errors = errors
                    continue
            commit_staging_to_sandbox()
            session.add_turn(user_text, reply['content'], sorted(changed))
            yield sse('files_updated', {'files': read_committed_files()})
            yield sse('assistant_message', {'text': reply['content']})
            return

        # The model asked for tools: run them in order.
        last_tool_message = None
        for call in reply['tool_calls']:
            result = run_tool(call['name'], call['args'], changed)
            ok = not result.startswith('ERROR:')
            yield sse('tool_call', {'name': call['name'], 'path': call['args'].get('path'), 'ok': ok})
            last_tool_message = {'role': 'tool', 'tool_call_id': call['id'], 'content': result}
            messages.append(last_tool_message)

        # Check the project after every step that ran tools.
        yield sse('status', {'phase': 'validating'})
        errors = run_tsc()
        if errors == '':
            checked_clean = True
        else:
            checked_clean = False
            fix_retries += 1
            if fix_retries > MAX_FIX_RETRIES:
                break
            note = NL + 'Compiler check FAILED:' + NL + errors
            if errors == last_errors:
                note += NL + 'This is the same error as before. Your last change did not fix it, try a different approach.'
            last_tool_message['content'] += note
            last_errors = errors
            yield sse('status', {'phase': 'fixing_error', 'attempt': fix_retries})

    # Out of steps or fix attempts. Nothing was committed, so the preview is untouched.
    reset_staging_from_sandbox()
    detail = last_errors[:500]
    if detail == '':
        detail = 'The step limit was reached.'
    session.add_turn(user_text, 'Turn failed and was rolled back.', [])
    yield sse('error', {'message': 'I could not finish this change cleanly, so I rolled it back. ' + detail})
```

Note the two rules that make this safe. First, only the gate at the bottom copies files into the sandbox. Second, the compiler runs after a whole step of tool calls, not after each single call, because a half-finished step often fails for reasons the model has not had time to fix yet (for example `App.tsx` imports a component that is created one call later).

### 8.6 Talking to the LLM

```python
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

load_dotenv(Path(__file__).resolve().parents[2] / '.env')   # the .env at the repo root
client = OpenAI(base_url=os.environ['LLM_BASE_URL'], api_key=os.environ['LLM_API_KEY'])


def with_retry(fn):
    wait = 2
    for attempt in range(1, 5):
        try:
            return fn()
        except RateLimitError:
            if attempt == 4:
                raise
            time.sleep(wait)
            wait = wait * 2


def call_llm(messages):
    def create():
        return client.chat.completions.create(
            model=os.environ['LLM_MODEL'],
            messages=messages,
            tools=TOOL_DEFINITIONS,
            temperature=0.2,
        )

    response = with_retry(create)
    message = response.choices[0].message
    tool_calls = []
    for c in message.tool_calls or []:
        try:
            args = json.loads(c.function.arguments or '{}')
        except ValueError:
            args = {'_bad_json': True}
        tool_calls.append({'id': c.id, 'name': c.function.name, 'args': args})
    return {
        'raw_message': message.model_dump(exclude_none=True),
        'content': message.content or '',
        'tool_calls': tool_calls,
    }
```

When a 429 happens, also send a status event ('waiting for the rate limit') so the user sees why it is slow.

### 8.7 Context and memory

The server keeps one in-memory session. It stores `history`: for each past turn, the user's request and a short assistant note, such as 'Added a dark mode toggle. Files changed: App.tsx, Header.tsx'. Raw tool calls and old file dumps from earlier turns are not stored. Keep only the last 10 entries.

Every new request is sent as the user message with the current committed files attached. Because the project is small, giving the model the files directly saves it from spending requests on `read_file`.

```python
def build_user_message(text):
    files = read_committed_files()   # {'src/App.tsx': '...'}
    snapshot = ''
    for name in files:
        snapshot += '=== ' + name + ' ===' + NL + files[name] + NL
    if len(snapshot) > 30000:
        snapshot = 'Files are too large to show. File list: ' + ', '.join(files.keys()) + '. Use read_file.'
    return 'Current project files:' + NL + snapshot + NL + 'User request: ' + text
```

The 30000 character cap protects the rate limit and keeps token cost down. A failed turn is also recorded in the history so the model knows it did not happen.

### 8.8 System prompt

Keep it constant between turns. Put it in `prompts.py`.

```
You are UI Agent. You build and edit a small React + TypeScript + Tailwind UI by calling tools.

Rules:
1. All code lives in src/. The entry is src/App.tsx with a default export named App. Never touch main.tsx or index.css.
2. Only these packages exist: react, react-dom, lucide-react, recharts, framer-motion, clsx, tailwind-merge. Style with Tailwind classes. Do not import anything else. Do not call external APIs, use mock data written in the code.
3. For a new UI: think briefly, then create files. Split the UI into small components in src/components/.
4. For follow-ups: change only what was asked. Use edit_file on existing files. Do not rewrite or delete files that do not need changes.
5. After your changes the system compiles the project and shows you any errors. Fix them.
6. When you are done, reply with 1 to 3 sentences describing what changed. Do not put code in the final reply.
```

### 8.9 HTTP API and streaming

| Route | Purpose |
| --- | --- |
| `POST /api/chat` | Body `{ message }`. Responds as an event stream. Returns 409 if a turn is already running |
| `GET /api/files` | Committed files as `{ 'src/App.tsx': '...' }` |
| `POST /api/reset` | Restores the starter App, clears history |

Events are text blocks: `event: tool_call`, then ` data:  ` followed by a JSON string made with `json.dumps`, then a blank line. Use these names only: `status`, `tool_call`, `files_updated`, `assistant_message`, `error`. The `sse()` helper in section 8.5 builds each block. The route wraps the `run_turn` generator in a `StreamingResponse`. Make it a plain `def` route, not `async def`, so FastAPI runs it in a worker thread and the slow model and compiler calls do not freeze the server. The lock produces the 409 for a second request.

```python
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.agent import run_turn, sse
from app.sessions import Session

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:5173'],
    allow_methods=['*'],
    allow_headers=['*'],
)

turn_lock = threading.Lock()
session = Session()


class ChatRequest(BaseModel):
    message: str


@app.post('/api/chat')
def chat(body: ChatRequest):
    if not turn_lock.acquire(blocking=False):
        return JSONResponse({'error': 'A turn is already running'}, status_code=409)

    def stream():
        try:
            for event in run_turn(session, body.message):
                yield event
        except Exception as err:
            yield sse('error', {'message': str(err)})
        finally:
            turn_lock.release()

    return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache'})
```

The prototype is single-user: there is one sandbox folder, so there is one session. Say so in the README. If the server restarts, the files on disk survive but the chat history is lost.

### 8.10 Client behavior

- The browser's built-in `EventSource` only supports GET requests, so it cannot be used for a POST. Use `fetch` and read the body as a stream:

```ts
async function sendMessage(text: string, onEvent: (name: string, data: any) => void) {
  const res = await fetch('http://localhost:8000/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: text }),
  });
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const result = await reader.read();
    if (result.done) break;
    buffer += decoder.decode(result.value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() || '';
    for (const part of parts) {
      const lines = part.split('\n');
      const name = lines[0].replace('event: ', '');
      const data = JSON.parse(lines[1].replace('data: ', ''));
      onEvent(name, data);
    }
  }
}
```

- Disable the send button while a turn runs.
- Show tool calls as small pills, for example 'edit\_file src/App.tsx, ok'.
- Load `GET /api/files` on page load so a refresh keeps the code view.
- After `files_updated`, reload the iframe by changing a `key` on it (Vite also refreshes by itself).
- Listen for runtime errors from the preview:

```ts
window.addEventListener('message', (event) => {
  if (event.origin !== 'http://localhost:5174') return;
  if (event.data && event.data.type === 'SANDBOX_RUNTIME_ERROR') {
    setRuntimeError(event.data);
  }
});
```

When set, show a banner with a 'Ask the agent to fix this' button. Clicking it sends an ordinary chat message containing the error message and stack, so it goes through the same loop and the same commit gate.

## 9. OpenAI API and cost plan

- You need a paid OpenAI API key with enough credit for the build day (agent turns, eval, and demos). Put it in `.env`; never commit it.
- Default model is `gpt-4o-mini` (tool calling, lower cost). Change `LLM_MODEL` in `.env` if you prefer another OpenAI chat model.
- Before a long eval run, check OpenAI's current rate limits (RPM / TPM) for your account tier.
- A turn uses about 2 to 8 model calls. Plan for roughly a call every few seconds at most.
- Backoff on HTTP 429 is already in `llm.py`. Log token usage for each call to the server terminal.
- Everything else is local and free: Node, Vite, Tailwind, the compiler, and git. No database, no cloud sandbox, no hosting.

## 10. Build plan in increments

One increment equals one git branch equals one tag. Rough time: 9 hours plus buffer. Never start the next increment before the check of the current one passes.

| Tag | Increment | Time |
| --- | --- | --- |
| v0.0-setup | Repo, rules, ignore files | 20 min |
| v0.1-sandbox | Preview project with error boundary | 45 min |
| v0.2-tools | Tools, compiler check, commit and rollback, no LLM yet | 1.5 h |
| v0.3-agent-cli | Agent loop, run from the terminal | 1.5 h |
| v0.4-http | FastAPI routes and streaming | 45 min |
| v0.5-client | Chat UI, code view, preview | 2 h |
| v0.6-runtime-errors | Runtime error banner and fix button | 30 min |
| v1.0 | Eval, README, demo | 1.5 h |

**v0.0-setup.** `git init`, `.gitignore`, `.env.example`, `docs/SPEC.md`, `AGENTS.md`, root `package.json`. Check: `git check-ignore .env` prints `.env`, and `git status` is clean after the commit.

**v0.1-sandbox.** Create `sandbox/` with Vite's React TypeScript template, add the allowed packages and Tailwind, apply section 7 (config, trusted `main.tsx`, `index.css`). Put a hard-coded hello `App.tsx` in `server/template/src/`. Check: the page loads at port 5174. Temporarily make `App` throw: the red card shows, and when embedded in the host page the message appears in its console. Revert the throw.

**v0.2-tools.** In `server/app/`: `workspace.py` (create `sandbox/.staging` and its tsconfig, copy sandbox to staging, commit staging to sandbox by writing changed files and deleting removed ones, read files), `tools.py`, `validate.py`. Add `server/scripts/test_tools.py`, which asserts: creating a file works; a missing `old_str` returns an error; a duplicate `old_str` returns an error; `../x` is rejected; writing `main.tsx` is rejected; overwriting a long existing file is rejected; the template compiles clean; after writing `const x: number = 'a'` the compiler reports an error; commit copies files; rollback restores. Check: `cd server && python -m scripts.test_tools` prints PASS for every line. This is the cheapest bug-catching step in the whole project, so do not skip it.

**v0.3-agent-cli.** Add `llm.py`, `prompts.py`, `sessions.py`, `agent.py`, and `scripts/cli.py`, a small terminal loop that reads a line, runs one turn in one session, and prints every event. Start it with `cd server && python -m scripts.cli`. Check, all three: (a) a 'create' prompt commits files and the preview at 5174 changes; (b) a follow-up like 'make the main button green' touches only the files it needs, and the CLI prints the list of changed files; (c) the demo prompt from section 13 shows at least one compiler error followed by a fix in the log.

**v0.4-http.** `main.py` with the three routes (section 8.9), CORS limited to `http://localhost:5173`, and the 409 rule. Check: `curl -N -X POST http://localhost:8000/api/chat -H 'Content-Type: application/json' -d '{"message":"make a counter"}'` prints a stream of events, `GET /api/files` returns JSON, and a second request during a running turn gets 409.

**v0.5-client.** Build section 8.10 and the split layout: chat on the left, tabs 'Preview' and 'Code' on the right, a flat file list plus a plain `<pre>` viewer, a 'New session' button calling `/api/reset`. After this tag, add no new features, only fixes. Check: the full flow in the browser, and a deliberately failing turn leaves the preview unchanged and shows the error in the chat.

**v0.6-runtime-errors.** The banner and fix button from section 8.10. Check: ask for a button whose click reads a property of `undefined`, click it, see the banner, click fix, see the agent repair it.

**v1.0.** `scripts/eval.py`, `eval/results.md`, the README, the demo recording. Check: section 16.

## 11. Git workflow and rollback

`main` must always contain the last working version.

```
git switch -c inc/2-tools          # start an increment on its own branch
# ... agent works, commits small steps ...
# when the increment check passes:
git switch main
git merge inc/2-tools
git tag v0.2-tools
```

Commit messages start with a word: `feat:`, `fix:`, `test:`, `docs:` or `chore:`. Several small commits per increment are good, since the assignment wants commits that show how it was built. Do not squash.

When an increment goes wrong:

```
git switch main                    # main is untouched, still the last good version
git branch -D inc/2-tools          # throw the failed attempt away and retry
```

If you merged something bad into `main`:

```
git switch -c recover v0.2-tools   # new branch from the last good tag, safest
# or, if you are sure: git reset --hard v0.2-tools   (deletes later commits)
```

Before asking the agent to try something risky, run `git status` and make sure it is clean. Never commit `.env`.

## 12. Rules for the local agent (copy into AGENTS.md)

```
# Rules for the coding agent
- Read docs/SPEC.md first. The assignment table in section 2 is the source of truth.
- Work on exactly one increment at a time, on its own branch inc/N-name. Do not start the next one.
- Keep code simple and plain: small functions, no clever syntax, no new libraries unless SPEC.md lists them.
- Server code is Python 3.11+. Use plain functions and simple loops. Run server commands from the server folder with the virtual environment active.
- Never add features outside SPEC.md section 3 (in scope). If something seems missing, stop and ask.
- Never edit sandbox locked files (section 8.1) except in the increments that create them.
- Never commit .env or API keys. Never print keys in logs.
- When the increment is done: run its check from SPEC.md section 10, show the output, commit with a clear message, and stop.
- Do not merge or tag. Parv does that after reviewing.
- If a check fails twice, stop and explain what you tried instead of piling on more changes.
```

Prompt template to start each increment:

```
Read AGENTS.md and docs/SPEC.md. Implement increment v0.N-name only, as described in section 10.
Create branch inc/N-name. Run the check for this increment and show me the output. Commit and stop.
```

## 13. Evaluation and demo

### Eval set

| # | Kind | Prompt |
| --- | --- | --- |
| 1 | Form | Contact form with name, email and message, validation, and a success message |
| 2 | Dashboard | Finance dashboard with summary cards, a bar chart of spending, and a transactions table with mock data |
| 3 | Landing page | Landing page for a fictional coffee brand with hero, features, pricing and footer |
| 4 | Small app | Todo app with add, complete, delete and filter |
| 5 | Small app | Pomodoro timer with start, pause and reset |
| 6 | Form | Login and sign-up screen with a toggle between them |
| 7 | Small app | Kanban board with 3 columns and buttons to move cards |
| 8 | Dashboard | Weather card UI with mock data and a Celsius or Fahrenheit toggle |
| F1 | Follow-up on 2 | Add a dark mode toggle in the header |
| F2 | Follow-up on 4 | Show how many tasks are left |
| F3 | Follow-up on 3 | Change the main color to green and add a testimonials section |
| F4 | Follow-up on 1 | Make the message field optional |

`scripts/eval.py` runs each prompt in a fresh session (reset first), waits a few seconds between calls to respect the rate limit, and writes `eval/results.md` with these columns: prompt, build passed, model calls used, fix attempts, seconds, and for follow-ups, which files changed. Success means: all 12 end in a clean commit, and each follow-up changes only files related to the request. Report the real numbers, even if some fail.

### Demo recording (3 to 4 minutes)

1. Create a UI from a prompt, for example the finance dashboard.
2. Send a follow-up edit, for example the dark mode toggle, and point out in the code view that only a few lines changed.
3. Show the error recovery. A reliable way to trigger one: ask for 'use the date-fns library to show relative dates'. That package is not installed, so the compiler reports a missing module, the log shows the retry, and the agent replaces it with plain code. Keep this prompt as a backup in case the model never makes a natural mistake.
4. Optionally show the runtime error banner.

## 14. README outline, trade-offs, known limits

README order: title and one-line pitch, demo link, setup commands, architecture diagram, how the agent loop and tools work, design decisions and trade-offs, eval results, known limits, what I would build next.

Setup commands for the README:

```
git clone <repo-url> && cd ui-agent
cp .env.example .env      # then paste your free API key into .env
python -m venv .venv      # then activate it: source .venv/bin/activate (Windows: .venv\Scripts\activate)
npm run setup && npm run dev
```

Trade-offs to write down:

- One loop with 4 tools instead of several AI agents: fewer model calls, easier to debug, keeps API cost down. Split only if evaluation shows a benefit.
- A Python server with Node only for the preview and the compiler: the server is written in the language I move fastest in, at the cost of two runtimes to install.
- A local Vite sandbox instead of a cloud sandbox: free and fast hot reload, but only one session at a time and no arbitrary packages.
- Compiler check instead of running the app on the server: fast and deterministic, but it cannot catch runtime bugs, which is why the preview reports crashes.
- Search-and-replace edits instead of diffs: models handle exact strings better than line-numbered patches.
- Fixed package list: removes made-up imports, limits what can be built.
- In-memory session: no database needed, history is lost on restart.
- Files shown directly in the prompt: saves model calls, costs tokens, so it is capped.

Known limits: single user and single session; generated code can reach the public internet; the commit copies files one by one so the preview may flash an in-between state for a moment; smaller models sometimes ignore the package list; complex interactions such as drag and drop may fail within 3 fix attempts; no undo.

Next steps: per-session sandboxes, an undo button backed by a git repo inside the sandbox, running the sandbox in the browser with a tool like Sandpack so it can be hosted, a screenshot step so the model can see its own output, and a parallel eval run.

## 15. Risks and what to cut

| Risk | Plan |
| --- | --- |
| OpenAI rate limit (429) or high token spend | Backoff in `llm.py`, keep prompts small, stick to `gpt-4o-mini` unless a stronger model is needed |
| Model calls tools badly | Simple schemas, explicit prompt, try the other provider first |
| `tsc` is slow | `skipLibCheck`, call the binary directly, loose strictness |
| Wrong Python or missing packages | Activate the virtual environment first, then run `pip install -r server/requirements.txt` again |
| A port is taken | `strictPort` makes Vite fail loudly. For the server, pick a free port and update the client URL and the CORS setting |
| Running late | Cut in this order: framer-motion, history trimming (just keep the last 6 turns), the eval script (fill the table by hand), the runtime error button |

Never cut: the tools test, the commit gate with rollback, the README, the demo.

## 16. Definition of done

- [ ] Fresh clone runs with the README commands
- [ ] `.env` is not in git, `.env.example` is
- [ ] Create, follow-up edit and automatic error recovery all work in the browser
- [ ] A failed turn leaves the preview and code view unchanged
- [ ] `test:tools` passes
- [ ] `eval/results.md` has real numbers
- [ ] README has every section from section 14
- [ ] Demo video shows a multi-turn session with one recovered error
- [ ] Tags v0.0 to v0.6 and v1.0 exist, `main` is the final version

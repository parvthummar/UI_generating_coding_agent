# UI Agent

Chat on the left, a live React preview on the right. You describe a UI, an agent writes the code, the TypeScript compiler checks it, and the preview updates only after that check is clean.

Demo: not recorded in this repo. A 3 to 4 minute walkthrough is listed under [Demo script](#demo-script).

## Setup

You need Python 3.11+, Node 20+, and an OpenAI API key.

```bash
git clone <repo-url> && cd ui-agent
cp .env.example .env
python -m venv .venv
```

Activate the virtual environment, then paste your OpenAI API key into `.env`:

```bash
source .venv/bin/activate          # Windows: .venv\Scripts\activate
npm run setup && npm run dev
```

On Windows PowerShell, copy the env file with `copy .env.example .env` if `cp` is not available.

`npm run setup` installs the root, client, and sandbox packages, installs the Python requirements, and resets the sandbox to the starter screen. `npm run dev` starts the host app on port 5173, the preview on port 5174, and the API on port 8000.

Open http://localhost:5173.

This is a single-user prototype. There is one sandbox folder and one in-memory chat session. If the server restarts, the files on disk stay and the chat history is gone.

## Architecture

```
Browser  localhost:5173          Sandbox  localhost:5174
chat, status, code view          Vite + React preview
        |                                ^
        | POST /api/chat (SSE)           | commit copies files
        v                                |
Server  localhost:8000  -----------------+
one agent loop, four tools, tsc gate
        |
        v
OpenAI API
```

The preview is a different origin because it is a different port. That is what isolates it from the host page. The iframe `sandbox` attribute, with `allow-same-origin`, would not be enough on the same origin. The API allows CORS only from `http://localhost:5173`, so preview code cannot call the API. Generated code can still reach the public internet.

Router, editor, debugger, and reviewer are not separate agents. They are modes of one loop, driven by the system prompt and the tool results.

## Agent loop and tools

One turn:

1. Copy `sandbox/src` to `sandbox/.staging/src`.
2. Send the system prompt, a short history, and a snapshot of the current files.
3. The model chooses tools. The server runs them on the staging copy. At most 8 model calls, and at most 4 tool calls per step.
4. After each step of tool calls, `tsc --noEmit` runs. Compiler errors go back to the model, up to 3 fix attempts.
5. When the model stops and the compiler is clean, staging is copied onto `sandbox/src`. The preview refreshes.
6. If the step limit or the fix limit is hit, staging is dropped. The preview stays as it was, and the chat says the turn was rolled back.

Tools:

| Tool | What it does |
| --- | --- |
| `read_file` | Returns the text of a file under `src/` |
| `write_file` | Creates a file. Refuses to overwrite a file longer than 60 lines |
| `edit_file` | Replaces one exact string. Use this for follow-up edits |
| `delete_file` | Deletes a file. Refuses `App.tsx` |

`main.tsx` and `index.css` are locked. Paths must stay inside `sandbox/.staging/src`. Only `.ts` and `.tsx` files can be written.

There is no tool for the compiler. The server runs it, so the model cannot skip the check.

## Design decisions and trade-offs

- One loop with 4 tools instead of several AI agents: fewer model calls, easier to debug, keeps API cost down. Split only if evaluation shows a benefit.
- A Python server with Node only for the preview and the compiler: the server is written in the language I move fastest in, at the cost of two runtimes to install.
- A local Vite sandbox instead of a cloud sandbox: free and fast hot reload, but only one session at a time and no arbitrary packages.
- Compiler check instead of running the app on the server: fast and deterministic, but it cannot catch runtime bugs, which is why the preview reports crashes.
- Search-and-replace edits instead of diffs: models handle exact strings better than line-numbered patches.
- Fixed package list: removes made-up imports, limits what can be built. The preview already has react, react-dom, lucide-react, recharts, framer-motion, clsx, tailwind-merge, and Tailwind.
- In-memory session: no database needed, history is lost on restart.
- Files shown directly in the prompt: saves model calls, costs tokens, so it is capped at 30000 characters.

## Eval results

The script is `server/scripts/eval.py`. From the `server` folder, with the virtual environment active:

```bash
python -m scripts.test_tools
python -m scripts.eval
```

`scripts.eval` resets the sandbox before each new UI, then runs that prompt's follow-up in the same session. It waits 5 seconds between model turns. The table it writes is in [eval/results.md](eval/results.md). Numbers below are copied from that file after the run recorded in this commit.

The recorded run finished **11 of 12** prompts with a clean commit. The finance dashboard hit the step limit after 8 model calls and 3 fix attempts, and was rolled back. Its follow-up (dark mode toggle) then edited the starter app, not a dashboard. The other follow-ups changed only the files the request needed. Full table: [eval/results.md](eval/results.md).

## Known limits

Single user and single session. Generated code can reach the public internet. The commit copies files one by one, so the preview may flash an in-between state for a moment. Smaller models sometimes ignore the package list. Complex interactions such as drag and drop may fail within 3 fix attempts. There is no undo.

## What I would build next

Per-session sandboxes, an undo button backed by a git repo inside the sandbox, running the sandbox in the browser with a tool like Sandpack so it can be hosted, a screenshot step so the model can see its own output, and a parallel eval run.

## Demo script

1. Create a UI, for example the finance dashboard.
2. Send a follow-up, for example a dark mode toggle, and show in the code view that only a few lines changed.
3. Ask to use the `date-fns` library to show relative dates. That package is not installed. The compiler reports a missing module, the log shows a retry, and the agent replaces it with plain code.
4. Optionally click a control that crashes the preview, then use **Ask the agent to fix this**.

## Checks

```bash
git check-ignore .env
cd server && python -m scripts.test_tools
```

# UI Agent

Chat on the left, a live React preview on the right. You describe a UI, an agent writes the code, and the preview updates only after the staged project passes TypeScript, a production build, and a browser smoke test. Follow-ups edit the existing code with small search-and-replace edits instead of rewriting it.

Demo: not recorded in this repo. A 3 to 4 minute walkthrough is listed under [Demo script](#demo-script).

## Setup

You need Python 3.11+, Node 20+, and an OpenAI API key.

```bash
git clone https://github.com/parvthummar/UI_generating_coding_agent.git && cd UI_generating_coding_agent
cp .env.example .env
python -m venv .venv
```

Activate the virtual environment, then paste your OpenAI API key into `.env`:

```bash
source .venv/bin/activate          # Windows: .venv\Scripts\activate
npm run setup && npm run dev
```

On Windows PowerShell, copy the env file with `copy .env.example .env` if `cp` is not available.

`npm run setup` installs the root, client, and sandbox packages, downloads the Playwright Chromium build used by the smoke test (`npx playwright install chromium` in `sandbox/`), installs the Python requirements, and resets the sandbox to the starter screen. `npm run dev` starts the host app on port 5173, the preview on port 5174, and the API on port 8000.

The smoke test needs that Chromium build. If validation reports that the browser is missing, run `npx playwright install chromium` from `sandbox/`.

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
one agent loop, four tools, staged validation
        |
        v
OpenAI API
```

The preview is a different origin because it is a different port. That is what isolates it from the host page. The iframe `sandbox` attribute, with `allow-same-origin`, would not be enough on the same origin. The API allows CORS only from `http://localhost:5173`, so preview code cannot call the API. The preview also sends a Content-Security-Policy that allows connections only to itself, and Vite is not allowed to serve files outside the sandbox folder, so the preview cannot read the API key or call the public internet. The iframe does not receive camera, microphone, or geolocation permission. This is browser isolation, not a separate virtual machine or operating-system sandbox. The smoke test launches a separate headless browser against the staged build. It does not run generated code inside the host app.

Router, editor, debugger, and reviewer are not separate agents. They are modes of one loop, driven by the system prompt and the tool results.

## Agent loop and tools

One turn:

1. Copy `sandbox/src` to `sandbox/.staging/src`. The agent only ever writes to the staging copy.
2. Send the system prompt, the last 10 turns of history (each request plus a short note of what changed, or that it failed), and the request with the current source of every project file attached. If the files exceed 30,000 characters, the rest are listed by path and description and the model uses `read_file`. When the project is still the blank starter, the message says so.
3. The model chooses tools. The server runs every tool call of a step in order on the staging copy (up to 12 per step). After a step that changed files, `tsc` runs and any errors go back to the model with the offending source lines quoted. If a component exists but is not imported, the error comes with the exact import line. These mid-build errors are feedback, not failures: a half-built UI that imports a component written one step later is normal. If an error repeats one seen earlier in the turn, the model also gets the current text of the files involved, which breaks edit loops.
4. When the model stops calling tools, the server validates the staged tree: `tsc --noEmit`, then `vite build` with `sandbox/vite.staging.config.ts`, then a Playwright smoke test of that build. Clean means commit. A failure goes back to the model with the error text, the failing lines, and the current text of the cited files. At most 3 of these correction rounds, and at most 16 model calls in total. If the step budget runs out with a clean project, it still gets one final check.
5. Commit copies the staged source onto the sandbox. The preview refreshes, the code view updates from the same event, and the files changed in this turn are marked in the code view.
6. If the fix limit or step limit is hit, staging is dropped, the preview stays as it was, and the chat says the turn was rolled back. The history records the failure, so the next request knows that change never happened. The chat stays usable.

Tools:

| Tool | What it does |
| --- | --- |
| `read_file` | Returns the text of one file under `src/` |
| `write_file` | Creates a file or replaces it. A file that was already in the preview before this request and has more than 60 lines is refused, so follow-ups must use `edit_file`. Files created during the current request can be rewritten while the model fixes them |
| `edit_file` | Replaces one exact `old_str`. Zero or multiple matches is an error that includes the current file text. If the exact text is not found, a match that ignores leading and trailing spaces on each line is accepted when it is unique, which absorbs indentation drift. An edit that changes nothing is an error. Editing the blank starter `App.tsx` is refused, it must be replaced |
| `delete_file` | Deletes a file. Refuses `App.tsx` |

`main.tsx` and `index.css` are locked. Paths must stay inside `sandbox/.staging/src`. Only `.ts` and `.tsx` files can be written. An edit of one file does not touch other files.

There is no tool for the compiler, the build, or the smoke test. The server runs them, so the model cannot skip the check. The smoke test confirms that the staged UI mounts and that the error boundary or an uncaught exception did not fire. It does not click through the page. Clicks that crash later are reported by the preview, and **Ask the agent to fix this** sends the error and stack through the same commit gate.

## Design decisions and trade-offs

- One loop with 4 tools instead of several AI agents: fewer model calls, easier to debug, keeps API cost down.
- The current source goes into every request: the model edits what it can see, so it does not spend steps on `read_file` or guess at `old_str`. That costs tokens, so it is capped at 30,000 characters, after which files are listed by description and read on demand. An earlier version sent only a file catalog and required `read_file` before every edit. In the eval that gate rejected the very first write of every new UI and caused most rollbacks.
- Mid-build type errors are feedback, final-check failures are corrections: the loop used to count a repeated intermediate error as a correction round, so a UI still being written used up its 3 rounds before it was finished. Now only a failed final check counts.
- The 60-line rewrite limit applies to files the user already sees: it keeps follow-ups targeted, but the model can still rewrite a file it created minutes ago in the same request.
- A Python server with Node only for the preview and the checks: the server is written in the language I move fastest in, at the cost of two runtimes to install.
- A local Vite sandbox instead of a cloud sandbox: free and fast hot reload, but only one session at a time and no arbitrary packages.
- TypeScript, then a production build, then a headless smoke test, all against the staged copy: a type check alone used to commit UIs that crashed on load.
- Search-and-replace edits instead of diffs: models handle exact strings better than line-numbered patches. Ambiguous matches are rejected instead of editing the wrong copy.
- Fixed package list: removes made-up imports, limits what can be built. The preview has react, react-dom, lucide-react, recharts, framer-motion, clsx, tailwind-merge, and Tailwind.
- In-memory session: no database needed, history is lost on restart. Undo snapshots live on disk until a new session.

## Eval results

From the `server` folder, with the virtual environment active:

```bash
python -m scripts.test_tools
python -m scripts.eval
```

`scripts.test_tools` needs no API key. It covers the tools, the path jail, commit and rollback, the real compiler, build and smoke test, and scripted agent turns that replay the failure modes seen in earlier evals: a first write to the starter, a UI whose first step imports components written later, eight tool calls in one step, rewriting a broken file created in the same turn, a model toggling between two broken versions, a follow-up that must leave other files byte-for-byte unchanged, and a request right after a rollback. It also checks the browser interaction checker against working and deliberately broken fixtures.

`scripts.eval` calls the model. It resets the sandbox before each new UI and runs that prompt's follow-up in the same session against the committed UI. It records model calls, type-error steps, fix attempts, tool errors, and time. For follow-ups it records which files changed and the share of the previous lines that are still there, so a full rewrite would show up as a low number. For the todo follow-up, Pomodoro, Kanban, and weather prompts, a committed UI then gets a Playwright check that types, clicks, and reads the page. That check does not decide whether a turn commits. E1 asks for `date-fns`, which is not installed, to show self-correction.

The table is in [eval/results.md](eval/results.md). The latest run with `gpt-4o-mini`:

- New UIs: 9 of 9 committed. Follow-ups: 4 of 4 committed, each keeping 99 to 100 percent of the previous lines.
- Interaction checks: 4 of 4 passed (todo count, Pomodoro start/pause/reset, Kanban move, temperature unit).
- Self-correction: in several rows the type check caught the model's own errors mid-build (a made-up lucide icon, a missing import, `NodeJS` types, `date-fns`), and the model fixed them before the commit.

Runs are not deterministic. Over the repeated runs while fixing the loop, an occasional follow-up or Kanban generation still rolled back, and the checker once caught a generated board that deleted a card when moving it left from the first column. Before these fixes the same eval committed 3 of 12 rows.

## Known limits

Single user and single session. The preview's network policy is browser CSP, not a dedicated sandbox service, and the iframe is not an operating-system sandbox. The commit copies files one by one, so the preview may flash an in-between state for a moment. Smaller models sometimes ignore the package list or skip a requested feature. The smoke test checks the first render of the staged build, not every click, and the interaction checks only run in the eval. A completely different UI in the same session has to be built through edits once `App.tsx` is over 60 lines, so **New session** is the clean way to start over. Undo restores one committed snapshot at a time and is cleared by New session. API keys stay in `.env` and are not written into prompts or tool results.

## What I would build next

Per-session sandboxes, running the interaction checks as part of the commit gate for apps whose kind is known, a screenshot step so the model can see its own output, running the sandbox in the browser with a tool like Sandpack so it can be hosted, and a parallel eval run.

## Demo script

1. Create a UI, for example the finance dashboard.
2. Send a follow-up, for example a dark mode toggle. In the code view, the changed files are marked, and only a few lines changed.
3. Ask for an activity feed that uses the `date-fns` library. That package is not installed. The chat shows the type check reporting the missing module, and the agent replaces it with plain code before the commit.
4. Optionally click a control that crashes the preview, then use **Ask the agent to fix this**.

## Checks

```bash
git check-ignore .env
cd server && python -m scripts.test_tools
```

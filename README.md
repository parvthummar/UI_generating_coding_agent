# UI Agent

Chat on the left, a live React preview on the right. You describe a UI, an agent writes the code, and the preview updates only after the staged project passes TypeScript, a production build, and a browser smoke test. A clean type check is not treated as proof that the UI runs.

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

1. Copy `sandbox/src` to `sandbox/.staging/src`, and copy `sandbox/file_descriptions.json` with it. That JSON file lives outside `src/`, so it is not a generated source file.
2. Send the system prompt, a short history, and a file catalog of the committed UI. Each line is a path and a one-sentence description. Source code is not included.
3. The model chooses tools. The server runs them on the staging copy. At most 12 model calls to build the change, and at most 4 tool calls per step. `read_file` is required before changing a file that already exists. After a step that changed files, `tsc` reports errors immediately. That hint does not use up a correction round. The same TypeScript error on two steps in a row starts a correction round instead of letting the model repeat the edit. If the 12 build calls are used while files have changed, the server asks the model to stop and then runs validation once. That is one extra model call, not an open-ended extension.
4. When the model stops and files changed, or when that final check runs, the server validates the staged tree: `tsc --noEmit` on `sandbox/.staging`, then `vite build` with `sandbox/vite.staging.config.ts` (root `sandbox/.staging`, not the committed `sandbox/src`), then a Playwright smoke test of that build. When TypeScript says a name is missing, the correction text also lists matching exports in other staged files, or says to declare a local name in the file that uses it. It gets at most 3 correction rounds. Each failed check allows 4 more model calls, so the total is at most 24. A failure on the last build step can still be corrected.
5. When that full check is clean, staging source and descriptions are copied onto the sandbox. The preview refreshes. The previous committed source and descriptions are stored as a snapshot first.
6. If the step limit or the fix limit is hit, staging is dropped. The preview stays as it was. The chat says the turn was rolled back. Follow-ups stay paused until you retry that request or explicitly send a new UI, so a later message cannot edit the old preview as if the failed UI had been created.
7. Undo restores the previous snapshot, including descriptions. New session clears the snapshots and rewrites the starter descriptions.

The catalog is how the model picks files. `read_file` loads the source it needs. There is no `list_files` or `search_code` tool. Files with no description yet still appear, labeled `(no description yet)`. Descriptions for deleted or missing files are dropped. A corrupt descriptions file does not hide the project files.

Tools:

| Tool | What it does |
| --- | --- |
| `read_file` | Returns the text of one file under `src/` |
| `write_file` | Creates a file, or replaces one of 60 lines or fewer. Requires `path`, `content`, and a one-sentence `description` |
| `edit_file` | Replaces one exact `old_str`. Zero matches or more than one match is an error and does not change the file. Optional `description` updates the catalog when the file's job changes |
| `delete_file` | Deletes a file and its description. Refuses `App.tsx` |

`main.tsx` and `index.css` are locked. Paths must stay inside `sandbox/.staging/src`. Only `.ts` and `.tsx` files can be written. An edit of one file does not delete other files unless the model calls `delete_file`.

There is no tool for the compiler, the build, or the smoke test. The server runs them, so the model cannot skip the check. The smoke test confirms that the staged UI mounts and that the error boundary or an uncaught exception did not fire. It does not click through the page. Harmless warnings and blocked external network requests are not failures. The live preview on port 5174 keeps serving the last committed `sandbox/src` while this check runs. After a commit, the eval script can run a separate Playwright check that clicks through a todo, timer, board, or temperature control. That check does not decide whether the turn commits, and a successful mount is not an interaction pass.

## Design decisions and trade-offs

- One loop with 4 tools instead of several AI agents: fewer model calls, easier to debug, keeps API cost down. Split only if evaluation shows a benefit.
- A Python server with Node only for the preview and the compiler: the server is written in the language I move fastest in, at the cost of two runtimes to install.
- A local Vite sandbox instead of a cloud sandbox: free and fast hot reload, but only one session at a time and no arbitrary packages.
- TypeScript, then a production build, then a headless smoke test, all against the staged copy: a type check alone used to commit UIs that crashed on load. The smoke test only covers the initial mount, so a button can still throw later. The preview reports that crash, and **Ask the agent to fix this** sends the error and stack through the same commit gate.
- Search-and-replace edits instead of diffs: models handle exact strings better than line-numbered patches. Ambiguous matches are rejected instead of editing the wrong copy.
- Fixed package list: removes made-up imports, limits what can be built. The preview already has react, react-dom, lucide-react, recharts, framer-motion, clsx, tailwind-merge, and Tailwind.
- In-memory session: no database needed, history is lost on restart. Source snapshots and their descriptions for undo live on disk until a new session.
- A path-and-description catalog instead of pasting every file: the model selects relevant files, then calls `read_file`. That stays small when the project grows, at the cost of an extra read before each edit. Descriptions are stored in `file_descriptions.json` next to `src/`, not inside it.

## Eval results

The script is `server/scripts/eval.py`. From the `server` folder, with the virtual environment active:

```bash
python -m scripts.test_tools
python -m scripts.eval
```

`scripts.eval` resets the sandbox before each new UI. It runs that prompt's follow-up in the same session only if the initial generation committed, so the follow-up edits the UI that was just committed. If the initial generation rolls back, the follow-up is recorded as skipped and is not counted as an iterative-edit success or failure. A skipped follow-up is the same situation the server handles with `followup_blocked`: no model call, and the starter project is left alone. The script waits 5 seconds between model turns. It records tool errors, fix attempts, render outcome, and whether a rollback was a compiler failure, a build failure, a runtime failure, or the step limit. For the todo follow-up, Pomodoro, Kanban, and weather prompts, a committed UI then gets a separate browser interaction check.

The table is in [eval/results.md](eval/results.md). Read the rates there, not a single "N of 12". Initial generation and executed follow-ups have different denominators. A row that was skipped because the initial prompt failed is not part of the follow-up rate. A committed row passed the initial render. It is not automatically a functional-interaction pass.

The file is a fresh run on 2026-10-21 with `gpt-4o-mini`. Every commit in that run passed TypeScript, the staged production build, and the browser smoke test.

Initial generation: 5 of 8 committed. Follow-ups executed against a committed UI: 2 of 3 committed. Follow-ups skipped because the initial generation failed: 1. Rows with a clean commit: 7 of 12. That 7 of 12 mixes new UIs and follow-ups, so it is not the iterative-edit score. Initial-render validation passed for those 7 committed rows. Functional checks: 1 passed (todo remaining count) and 1 inconclusive (weather unit labels). Pomodoro and Kanban did not commit, so their interaction checks did not run. Step-limit rollbacks: 0. Four rows exhausted 3 compiler corrections, including Pomodoro (`duplicate identifier 'React'`) and Kanban (redeclared `todo` state). Those rollbacks left the starter preview in place.

## Known limits

Single user and single session. The preview's network policy is browser CSP, not a dedicated sandbox service, and the iframe is not an operating-system sandbox. The commit copies files one by one, so the preview may flash an in-between state for a moment. Smaller models sometimes ignore the package list. Complex interactions such as drag and drop may fail within 3 fix attempts. The smoke test checks the first render of the staged build, not every click. Undo restores one committed snapshot at a time, including file descriptions, and is cleared by New session. API keys stay in `.env` and are not written into prompts, tool results, or the descriptions file by the server.

## What I would build next

Per-session sandboxes, a hosted sandbox service if the preview needs stronger isolation than browser CSP, running the sandbox in the browser with a tool like Sandpack so it can be hosted, a screenshot step so the model can see its own output, and a parallel eval run.

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

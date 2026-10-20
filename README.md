# UI Agent

A local AI coding agent that turns plain-English UI requests into React interfaces. The workspace places chat on the left and a live preview on the right. The agent edits TypeScript/TSX files through tools, checks each tool step with the TypeScript compiler, and publishes changes to the preview only after a clean commit.

> **Demo:** A recorded demo is not included in this repository. A 3–4 minute walkthrough script is provided below.

## Features

- **Prompt-to-UI generation:** Build forms, dashboards, landing pages, and small interactive apps from natural-language requests.
- **Targeted follow-up edits:** Continue refining the committed UI without regenerating the entire project.
- **Compiler-gated changes:** Run `tsc --noEmit` during the agent loop and send compiler errors back for repair attempts.
- **Staged changes and rollback:** Work in a staging directory. If generation reaches its limits or fails, discard staging and keep the last committed preview.
- **Code inspection and undo:** Inspect generated source and restore the previous committed snapshot.
- **Preview error recovery:** Send a runtime error and stack trace back to the agent with **Ask the agent to fix this**.

## Requirements

- Python 3.11 or newer
- Node.js 20 or newer, including npm
- An OpenAI API key

## Setup

Run these commands from a terminal.

### 1. Clone the repository and create the environment file

```bash
git clone https://github.com/parvthummar/UI_generating_coding_agent.git
cd UI_generating_coding_agent
```

macOS/Linux:

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell prevents activation because of its execution policy, you can use Command Prompt instead and activate with `.venv\Scripts\activate.bat`.

### 2. Configure the API key

Open `.env` and replace the placeholder for `LLM_API_KEY` with your key. The example file also defines the model endpoint and model name:

```dotenv
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=your-api-key-here
```

Keep `.env` private and do not commit API keys.

### 3. Install dependencies and start the app

With the virtual environment activated, run this from the repository root:

```bash
npm run setup
npm run dev
```

`npm run setup` installs the root, client, and sandbox Node dependencies, installs the Python requirements, and resets the sandbox to its starter UI. `npm run dev` starts three local services:

| Service | Address | Purpose |
| --- | --- | --- |
| Host app | [http://localhost:5173](http://localhost:5173) | Chat, status, and code view |
| React preview | [http://localhost:5174](http://localhost:5174) | Generated UI |
| API server | `http://localhost:8000` | Agent loop and tool execution |

Open [http://localhost:5173](http://localhost:5173) in your browser.

> **Note:** `npm run setup` resets the sandbox to the starter screen. Run it during initial setup, or when you intentionally want to reset the local demo.

## Architecture

```text
Browser — localhost:5173                 Preview — localhost:5174
Chat, status, code view                   Vite + React UI
          |                                      ^
          | POST /api/chat (SSE)                  | committed files copied
          v                                      |
Python API — localhost:8000 --------------------+
One tool-calling agent loop + TypeScript gate
          |
          v
      OpenAI API
```

The host app and preview use different ports, so they run on different origins. The iframe sandbox and browser Content Security Policy (CSP) add restrictions to the preview. CORS is configured to allow the host app origin, and Vite is restricted to serving files from the sandbox. The iframe does not receive camera, microphone, or geolocation permission.

These are **browser-level protections, not a dedicated operating-system or virtual-machine sandbox**. Treat this as a local prototype, not a hardened environment for running untrusted code.

The router, editor, debugger, and reviewer are not separate agents. They are roles handled by one loop through its system prompt and tool results.

## How the agent loop works

For each user turn:

1. Copy the committed source from `sandbox/src` to `sandbox/.staging/src`, and copy the file catalog to `sandbox/.staging/catalog.json`.
2. Send the system prompt, short conversation history, and a catalog of committed paths and one-line descriptions. The initial prompt does not include the source of every file. It tells the model to call `read_file` before editing, including when the preview is still the starter screen.
3. Let the model select tools. The server executes them against staging and updates the staged catalog. Each turn is limited to **8 model calls**, with at most **4 tool calls per step**.
4. Run `tsc --noEmit` after each tool step. If TypeScript reports errors, send them back to the model for up to **3 fix attempts**. A compiler error also includes the current text of the files it names, so the model can repair them.
5. If the model finishes and the compiler is clean, copy the staged source and its catalog into the committed preview. Vite refreshes from the committed source.
6. If the call or repair limit is reached, discard the staged source and the staged catalog. The last committed preview and its descriptions remain unchanged. After a rollback, follow-up edits are paused until the failed request is retried or a new UI is explicitly requested.
7. Save a snapshot of the previous source and catalog before each clean commit. **Undo** restores both. Starting a new session clears the snapshots and rebuilds the catalog for the starter files.

The compiler is run by the server, not exposed as a model tool, so the model cannot skip the check. A clean TypeScript compile does not guarantee that every interaction will work at runtime; preview errors can be sent back to the same repair-and-commit flow.

### Available tools

| Tool | Purpose | Guardrail |
| --- | --- | --- |
| `read_file` | Read one file under `src/` and return its source, with the stored description | Restricted to the workspace. Locked files stay locked |
| `write_file` | Create a source file, or replace a file of 60 lines or fewer | A new file requires a one-sentence description. Longer files must be edited |
| `edit_file` | Replace an exact string | An optional description is stored only when the file's responsibility changes |
| `delete_file` | Delete a source file and remove its catalog entry | Refuses to delete `App.tsx` |

`main.tsx` and `index.css` are locked. File paths must stay inside `sandbox/.staging/src`, and the agent can write only `.ts` and `.tsx` files.

The file catalog is `server/data/catalog.json`. It sits outside `sandbox/src`, so the preview does not serve it and the file tools cannot edit it. Each entry is a source path, such as `src/App.tsx`, and one sentence about that file. Locked files are included so the model can see their role. A missing description is shown as a labeled fallback instead of failing the turn. Descriptions are clues for choosing files; the model still has to read the source before editing.

## Design decisions and trade-offs

- **One loop, four tools:** Keeps the control flow easier to inspect and limits extra model calls compared with splitting work across several agents.
- **Python API with a Node preview/compiler:** Python handles orchestration; Node runs Vite and the TypeScript compiler. Both runtimes are required.
- **Local Vite sandbox:** Fast feedback and no hosted sandbox cost, but only one shared sandbox/session is supported.
- **Compiler gate instead of server-side app execution:** Provides a repeatable TypeScript check, but runtime behavior still needs to be tested in the preview.
- **Exact-string edits:** The model uses search-and-replace for focused changes instead of line-numbered patches.
- **Fixed dependency set:** Reduces invalid imports but limits which libraries generated UIs can use. The preview includes React, React DOM, Lucide, Recharts, Framer Motion, `clsx`, `tailwind-merge`, and Tailwind.
- **In-memory conversation history:** No database is required, but chat history disappears when the server restarts. Source files remain on disk.
- **File catalog in the prompt:** The model first receives each path and a one-line description, then calls `read_file` for the files it intends to change. There is no fifth tool, no embedding index, and no extra model call that writes descriptions. The model supplies a description when it creates a file.

## Evaluation

The evaluation code is `server/scripts/eval.py`; its recorded results are in [`eval/results.md`](eval/results.md). The script resets the sandbox before each new UI prompt and runs its follow-up in the same session. It waits five seconds between model turns.

To run the tool tests and the model-backed evaluation, activate `.venv`, then run from the repository root:

```bash
cd server
python -m scripts.test_tools
python -m scripts.eval
```

The model-backed evaluation requires a valid API key and makes API calls, which may incur usage charges. Running it rewrites `eval/results.md`; results can vary by model and configuration.

### Recorded result

The run recorded in [`eval/results.md`](eval/results.md) produced **7 clean commits out of 12 prompts**. The landing page, todo app, pomodoro timer, login screen, kanban board, and weather card committed. The contact form and the finance dashboard were rolled back after 3 fix attempts, so their follow-ups were refused before a model call. The todo follow-up, "show how many tasks are left," also used 3 fix attempts and was rolled back. The landing-page follow-up committed. These are results from that run, not a guarantee for the next one.

The finance dashboard is a useful failure-recovery demonstration. Use a successful case such as the landing page to demonstrate iterative edits.

## Known limitations

- Single user, one shared sandbox, and one in-memory chat session.
- Browser CSP is not equivalent to a dedicated sandbox service or virtual machine.
- Files are copied into the committed preview one at a time, so a brief intermediate state may appear during a commit.
- Smaller models may ignore dependency constraints or struggle with complex interactions such as drag-and-drop within the repair limit.
- TypeScript compilation cannot catch every runtime error or confirm visual quality.
- Undo stores committed source snapshots and the matching descriptions. Both are cleared when a new session starts.
- File descriptions say what a file is for. They are not a search index and they do not prove how the source behaves.

## Demo walkthrough (3–4 minutes)

This is a suggested script, not a recorded demo. The steps below avoid assuming that the finance dashboard generation succeeds.

1. **Generate a UI:** Ask for a landing page for a fictional coffee brand with a hero, features, pricing, and footer. Show the chat, code view, and live preview.
2. **Make a targeted edit:** Ask to change the main color to green and add a testimonials section. Show that the preview updates after the compiler gate and inspect the changed files.
3. **Show the dependency constraint:** Ask to use `date-fns` for relative dates. It is not in the installed dependency set; show the compiler error and repair attempt rather than assuming the requested library will be installed.
4. **Show recovery behavior:** Request the finance dashboard. In the recorded run this request was rolled back after 3 fix attempts. Explain that the previous committed preview remains intact and that a follow-up edit is blocked until the failed request is retried or a new UI is explicitly requested.
5. **Optional runtime recovery:** If a generated control triggers a preview error, use **Ask the agent to fix this** and show the error going through the same commit gate.

## Final checks

Run these from the repository root before submitting:

```bash
git check-ignore .env
```

The command should report `.env` as ignored. Then, with `.venv` activated:

```bash
cd server
python -m scripts.test_tools
```

Only report test or evaluation results that you actually ran. Do not commit `.env` or API credentials.

## Possible next steps

- Create a separate sandbox and session per user.
- Use a hosted sandbox service if stronger isolation is required.
- Add screenshot-based visual feedback so the agent can inspect its rendered result.
- Run broader, repeatable evaluation across prompts and models.

## Rules for the local agent (copy into AGENTS.md)

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
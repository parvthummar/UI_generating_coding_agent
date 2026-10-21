# Eval results

Fresh run of `python -m scripts.eval` from the `server` folder on 2026-10-21, model `gpt-4o-mini`.
Each initial prompt starts from the starter project. A follow-up runs only after that prompt commits, in the same session, against the committed UI.
Passing the type check is not enough to commit: the staged project must also pass the production build and the browser smoke test.

Initial generation: 2 of 8 committed.
Follow-ups executed against a committed UI: 1 of 1 committed.
Follow-ups skipped because the initial generation did not commit: 3. These are not iterative-edit successes and are not in the follow-up denominator.
Rows with a clean commit: 3 of 12. That total mixes new UIs and follow-ups. Use the two rates above.
Initial-render validation passed for 3 of 12 rows. A commit requires the staged smoke test, so a committed row passed the initial render. A rolled-back row did not.
Functional interaction checks, only on the todo follow-up, Pomodoro, Kanban, and weather prompts when those UIs committed: 1 passed, 0 failed, 0 inconclusive, 0 not checked, 11 not run. A mount is not an interaction pass.
Step-limit rollbacks: 0. Compiler correction exhausted after 3 attempts: 5.

| # | Phase | Prompt | Result | Reason | Render | Interaction | Model calls | Fix attempts | Tool errors | Seconds | Files changed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | initial | Contact form with name, email and message, validation, and a success message | rolled_back | compiler | not_reached | not_run | 15 | 3 | 6 | 56.8 |  |
| F4 | follow-up | Make the message field optional | skipped | initial_failed | not_run | not_run | 0 | 0 | 0 | 0 |  |
| 2 | initial | Finance dashboard with summary cards, a bar chart of spending, and a transactions table with mock data | rolled_back | compiler | not_reached | not_run | 13 | 3 | 3 | 47.0 |  |
| F1 | follow-up | Add a dark mode toggle in the header | skipped | initial_failed | not_run | not_run | 0 | 0 | 0 | 0 |  |
| 3 | initial | Landing page for a fictional coffee brand with hero, features, pricing and footer | committed |  | pass | not_run | 12 | 2 | 3 | 39.4 | src/App.tsx, src/components/Features.tsx, src/components/Footer.tsx, src/components/Hero.tsx, src/components/Pricing.tsx |
| F3 | follow-up | Change the main color to green and add a testimonials section | committed |  | pass | not_run | 4 | 0 | 0 | 13.6 | src/App.tsx, src/components/Features.tsx, src/components/Footer.tsx, src/components/Testimonials.tsx |
| 4 | initial | Todo app with add, complete, delete and filter | rolled_back | compiler | not_reached | not_run | 12 | 3 | 7 | 38.6 |  |
| F2 | follow-up | Show how many tasks are left | skipped | initial_failed | not_run | not_run | 0 | 0 | 0 | 0 |  |
| 5 | initial | Pomodoro timer with start, pause and reset | rolled_back | compiler | not_reached | not_run | 13 | 3 | 4 | 39.2 |  |
| 6 | initial | Login and sign-up screen with a toggle between them | rolled_back | compiler | not_reached | not_run | 11 | 3 | 9 | 29.7 |  |
| 7 | initial | Kanban board with 3 columns and buttons to move cards | rolled_back | compiler | not_reached | not_run | 12 | 2 | 4 | 38.8 |  |
| 8 | initial | Weather card UI with mock data and a Celsius or Fahrenheit toggle | committed |  | pass | pass | 5 | 0 | 1 | 16.1 | src/App.tsx, src/components/WeatherCard.tsx, src/components/index.ts |

1: I could not finish this change cleanly, so I rolled it back. The preview is still the last committed UI. Follow-ups are paused until you retry or start a new UI. TypeScript check failed:
sandbox/.staging/src/components/ContactForm.tsx(135,1): error TS1128: Declaration or statement expected.
sandbox/.staging/src/components/ContactForm.tsx(202,1): error TS1128: Declaration or statement expected.
F4: Not executed. Initial prompt 1 did not commit, so this row is not an iterative-edit result. The server would refuse the follow-up before any model call.
2: I could not finish this change cleanly, so I rolled it back. The preview is still the last committed UI. Follow-ups are paused until you retry or start a new UI. TypeScript check failed:
sandbox/.staging/src/App.tsx(4,7): error TS2451: Cannot redeclare block-scoped variable 'App'.
sandbox/.staging/src/App.tsx(12,7): error TS2451: Cannot redeclare block-scoped variable 'App'.
sandbox/.staging/src/main.tsx(3,8): error TS1192: Module '"sandbox/.staging/src/App"' has no default export.
F1: Not executed. Initial prompt 2 did not commit, so this row is not an iterative-edit result. The server would refuse the follow-up before any model call.
4: I could not finish this change cleanly, so I rolled it back. The preview is still the last committed UI. Follow-ups are paused until you retry or start a new UI. TypeScript check failed:
sandbox/.staging/src/App.tsx(24,9): error TS2367: This comparison appears to be unintentional because the types '"all" | "incomplete"' and '"completed"' have no overlap.
F2: Not executed. Initial prompt 4 did not commit, so this row is not an iterative-edit result. The server would refuse the follow-up before any model call.
5: I could not finish this change cleanly, so I rolled it back. The preview is still the last committed UI. Follow-ups are paused until you retry or start a new UI. TypeScript check failed:
sandbox/.staging/src/App.tsx(2,10): error TS2305: Module '"./components/PomodoroTimer"' has no exported member 'PomodoroTimer'.
6: I could not finish this change cleanly, so I rolled it back. The preview is still the last committed UI. Follow-ups are paused until you retry or start a new UI. TypeScript check failed:
sandbox/.staging/src/App.tsx(23,1): error TS1005: '}' expected.
7: I could not finish this change cleanly, so I rolled it back. The preview is still the last committed UI. Follow-ups are paused until you retry or start a new UI. TypeScript check failed:
sandbox/.staging/src/App.tsx(4,8): error TS2304: Cannot find name 'KanbanBoard'.
8 interaction: The temperature unit or value changed.

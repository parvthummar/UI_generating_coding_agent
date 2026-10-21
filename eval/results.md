# Eval results

Fresh run of `python -m scripts.eval` from the `server` folder on 2026-10-21, model `gpt-4o-mini`.
Each initial prompt starts from the starter project. A follow-up runs only after that prompt commits, in the same session, against the committed UI.
Passing the type check is not enough to commit: the staged project must also pass the production build and the browser smoke test.

Initial generation: 5 of 8 committed.
Follow-ups executed against a committed UI: 2 of 3 committed.
Follow-ups skipped because the initial generation did not commit: 1. These are not iterative-edit successes and are not in the follow-up denominator.
Rows with a clean commit: 7 of 12. That total mixes new UIs and follow-ups. Use the two rates above.
Initial-render validation passed for 7 of 12 rows. A commit requires the staged smoke test, so a committed row passed the initial render. A rolled-back row did not.
Functional interaction checks, only on the todo follow-up, Pomodoro, Kanban, and weather prompts when those UIs committed: 1 passed, 0 failed, 1 inconclusive, 0 not checked, 10 not run. A mount is not an interaction pass.
Step-limit rollbacks: 0. Compiler correction exhausted after 3 attempts: 4.

| # | Phase | Prompt | Result | Reason | Render | Interaction | Model calls | Fix attempts | Tool errors | Seconds | Files changed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | initial | Contact form with name, email and message, validation, and a success message | rolled_back | compiler | not_reached | not_run | 14 | 3 | 6 | 48.4 |  |
| F4 | follow-up | Make the message field optional | skipped | initial_failed | not_run | not_run | 0 | 0 | 0 | 0 |  |
| 2 | initial | Finance dashboard with summary cards, a bar chart of spending, and a transactions table with mock data | committed |  | pass | not_run | 9 | 1 | 3 | 39.7 | src/App.tsx, src/components/FinanceDashboard.tsx, src/components/SpendingChart.tsx, src/components/SummaryCards.tsx, src/components/TransactionsTable.tsx |
| F1 | follow-up | Add a dark mode toggle in the header | rolled_back | compiler | not_reached | not_run | 9 | 3 | 1 | 23.0 |  |
| 3 | initial | Landing page for a fictional coffee brand with hero, features, pricing and footer | committed |  | pass | not_run | 7 | 1 | 2 | 31.8 | src/App.tsx, src/components/Features.tsx, src/components/Footer.tsx, src/components/Hero.tsx, src/components/Pricing.tsx |
| F3 | follow-up | Change the main color to green and add a testimonials section | committed |  | pass | not_run | 4 | 0 | 0 | 14.5 | src/App.tsx, src/components/Features.tsx, src/components/Footer.tsx, src/components/Testimonials.tsx |
| 4 | initial | Todo app with add, complete, delete and filter | committed |  | pass | not_run | 3 | 0 | 1 | 20.8 | src/App.tsx, src/components/TodoFilters.tsx, src/components/TodoInput.tsx, src/components/TodoList.tsx |
| F2 | follow-up | Show how many tasks are left | committed |  | pass | pass | 3 | 0 | 0 | 7.8 | src/App.tsx |
| 5 | initial | Pomodoro timer with start, pause and reset | rolled_back | compiler | not_reached | not_run | 14 | 3 | 6 | 41.3 |  |
| 6 | initial | Login and sign-up screen with a toggle between them | committed |  | pass | not_run | 7 | 1 | 4 | 25.1 | src/App.tsx, src/components/Login.tsx, src/components/SignUp.tsx |
| 7 | initial | Kanban board with 3 columns and buttons to move cards | rolled_back | compiler | not_reached | not_run | 14 | 3 | 7 | 51.5 |  |
| 8 | initial | Weather card UI with mock data and a Celsius or Fahrenheit toggle | committed |  | pass | inconclusive | 6 | 1 | 2 | 24.7 | src/App.tsx, src/components/WeatherCard.tsx |

1: I could not finish this change cleanly, so I rolled it back. The preview is still the last committed UI. Follow-ups are paused until you retry or start a new UI. TypeScript check failed:
sandbox/.staging/src/components/ContactForm.tsx(145,1): error TS1128: Declaration or statement expected.
F4: Not executed. Initial prompt 1 did not commit, so this row is not an iterative-edit result. The server would refuse the follow-up before any model call.
F1: I could not finish this change cleanly, so I rolled it back. The preview is still the last committed UI. Follow-ups are paused until you retry or start a new UI. TypeScript check failed:
sandbox/.staging/src/components/Header.tsx(1,27): error TS1127: Invalid character.
sandbox/.staging/src/components/Header.tsx(1,29): error TS1127: Invalid character.
sandbox/.staging/src/components/Header.tsx(1,30): error TS1435: Unknown keyword or identifier. Did you mean 'interface'?
sandbox/.staging/src/compo
F2 interaction: A task was added and a remaining count was visible.
5: I could not finish this change cleanly, so I rolled it back. The preview is still the last committed UI. Follow-ups are paused until you retry or start a new UI. TypeScript check failed:
sandbox/.staging/src/App.tsx(1,8): error TS2300: Duplicate identifier 'React'.
sandbox/.staging/src/App.tsx(3,8): error TS2300: Duplicate identifier 'React'.
7: I could not finish this change cleanly, so I rolled it back. The preview is still the last committed UI. Follow-ups are paused until you retry or start a new UI. TypeScript check failed:
sandbox/.staging/src/components/KanbanBoard.tsx(9,10): error TS2451: Cannot redeclare block-scoped variable 'todo'.
sandbox/.staging/src/components/KanbanBoard.tsx(9,16): error TS2451: Cannot redeclare block-scoped variable 'setTodo'.
sandbox/.staging/src/components/KanbanBoard.tsx(13,10): error TS2451: Cannot r
8 interaction: The control changed the page, but the unit labels were not both recognized.

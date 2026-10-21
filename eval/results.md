# Eval results

Fresh run of `python -m scripts.eval` from the `server` folder.
Each initial prompt starts from the starter project. A follow-up runs only after that prompt commits, in the same session, against the committed UI.
Passing the type check is not enough to commit: the staged project must also pass the production build and the browser smoke test.

Initial generation: 9 of 9 committed.
Follow-ups executed against a committed UI: 4 of 4 committed.
Follow-ups skipped because the initial generation did not commit: 0. These are not iterative-edit successes and are not in the follow-up denominator.
Rows with a clean commit: 13 of 13. That total mixes new UIs and follow-ups. Use the two rates above.
Initial-render validation passed for 13 of 13 rows. A commit requires the staged smoke test, so a committed row passed the initial render. A rolled-back row did not.
Functional interaction checks, only on the todo follow-up, Pomodoro, Kanban, and weather prompts when those UIs committed: 1 passed, 1 failed, 2 inconclusive, 0 not checked, 9 not run. A mount is not an interaction pass.
Step-limit rollbacks: 0. Compiler correction exhausted after 3 attempts: 0.

| # | Phase | Prompt | Result | Reason | Render | Interaction | Model calls | Fix attempts | Tool errors | Seconds | Files changed | Previous lines kept |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | initial | Contact form with name, email and message, validation, and a success message | committed |  | pass | not_run | 4 | 0 | 0 | 23.6 | src/App.tsx, src/components/ContactForm.tsx |  |
| F4 | follow-up | Make the message field optional | committed |  | pass | not_run | 2 | 0 | 0 | 8.5 | src/components/ContactForm.tsx | 99% |
| 2 | initial | Finance dashboard with summary cards, a bar chart of spending, and a transactions table with mock data | committed |  | pass | not_run | 5 | 0 | 0 | 35.5 | src/App.tsx, src/components/BarChart.tsx, src/components/SummaryCard.tsx, src/components/TransactionsTable.tsx |  |
| F1 | follow-up | Add a dark mode toggle in the header | committed |  | pass | not_run | 3 | 0 | 0 | 20.5 | src/App.tsx, src/components/ThemeToggle.tsx | 99% |
| 3 | initial | Landing page for a fictional coffee brand with hero, features, pricing and footer | committed |  | pass | not_run | 2 | 0 | 0 | 18.1 | src/App.tsx, src/components/Features.tsx, src/components/Footer.tsx, src/components/Hero.tsx, src/components/Pricing.tsx, src/components/types.ts |  |
| F3 | follow-up | Change the main color to green and add a testimonials section | committed |  | pass | not_run | 5 | 0 | 1 | 147.9 | src/App.tsx, src/components/Hero.tsx, src/components/Testimonials.tsx, src/components/types.ts | 99% |
| 4 | initial | Todo app with add, complete, delete and filter | committed |  | pass | not_run | 2 | 0 | 0 | 18.1 | src/App.tsx, src/components/TodoForm.tsx, src/components/TodoItem.tsx, src/components/TodoList.tsx |  |
| F2 | follow-up | Show how many tasks are left | committed |  | pass | fail | 3 | 0 | 0 | 16.8 | src/App.tsx, src/components/TodoCounter.tsx | 100% |
| 5 | initial | Pomodoro timer with start, pause and reset | committed |  | pass | inconclusive | 3 | 0 | 0 | 23.8 | src/App.tsx, src/components/Controls.tsx, src/components/Timer.tsx |  |
| 6 | initial | Login and sign-up screen with a toggle between them | committed |  | pass | not_run | 2 | 0 | 0 | 16.0 | src/App.tsx, src/components/Login.tsx, src/components/Signup.tsx |  |
| 7 | initial | Kanban board with 3 columns and buttons to move cards | committed |  | pass | inconclusive | 6 | 0 | 0 | 28.1 | src/App.tsx, src/components/Card.tsx, src/components/KanbanBoard.tsx |  |
| 8 | initial | Weather card UI with mock data and a Celsius or Fahrenheit toggle | committed |  | pass | pass | 2 | 0 | 0 | 14.7 | src/App.tsx, src/components/WeatherCard.tsx, src/components/WeatherList.tsx |  |
| E1 | initial | Activity feed with 5 mock events that uses the date-fns library to show relative dates | committed |  | pass | not_run | 3 | 0 | 0 | 16.1 | src/App.tsx, src/components/ActivityFeed.tsx |  |

F2 interaction: The new task did not appear in the task list.
5 interaction: Start, pause, and reset were not all found.
7 interaction: No card could be tied to a single column.
8 interaction: The temperature unit or value changed.

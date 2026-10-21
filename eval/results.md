# Eval results

Fresh run of `python -m scripts.eval` from the `server` folder on 2026-10-21, model `gpt-4o-mini`.
Each initial prompt starts from the starter project. A follow-up runs only after that prompt commits, in the same session, against the committed UI.
Passing the type check is not enough to commit: the staged project must also pass the production build and the browser smoke test.

Initial generation: 6 of 8 committed.
Follow-ups executed against a committed UI: 4 of 4 committed.
Follow-ups skipped because the initial generation did not commit: 0. These are not iterative-edit successes and are not in the follow-up denominator.
Rows with a clean commit: 10 of 12. That total mixes new UIs and follow-ups. Use the two rates above.

| # | Phase | Prompt | Result | Reason | Model calls | Fix attempts | Tool errors | Seconds | Files changed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | initial | Contact form with name, email and message, validation, and a success message | committed |  | 8 | 2 | 1 | 27.7 | src/App.tsx, src/components/ContactForm.tsx |
| F4 | follow-up | Make the message field optional | committed |  | 3 | 0 | 0 | 6.4 | src/components/ContactForm.tsx |
| 2 | initial | Finance dashboard with summary cards, a bar chart of spending, and a transactions table with mock data | committed |  | 5 | 0 | 1 | 25.4 | src/App.tsx, src/components/FinanceDashboard.tsx, src/components/SpendingChart.tsx, src/components/SummaryCards.tsx, src/components/TransactionsTable.tsx |
| F1 | follow-up | Add a dark mode toggle in the header | committed |  | 5 | 0 | 0 | 14.6 | src/components/FinanceDashboard.tsx, src/components/Header.tsx |
| 3 | initial | Landing page for a fictional coffee brand with hero, features, pricing and footer | committed |  | 9 | 3 | 3 | 33.9 | src/App.tsx, src/components/Features.tsx, src/components/Footer.tsx, src/components/Hero.tsx, src/components/Pricing.tsx |
| F3 | follow-up | Change the main color to green and add a testimonials section | committed |  | 7 | 1 | 1 | 126.3 | src/App.tsx, src/components/Features.tsx, src/components/Footer.tsx, src/components/Testimonials.tsx |
| 4 | initial | Todo app with add, complete, delete and filter | committed |  | 3 | 0 | 1 | 18.7 | src/App.tsx, src/components/TodoFilters.tsx, src/components/TodoInput.tsx, src/components/TodoList.tsx |
| F2 | follow-up | Show how many tasks are left | committed |  | 6 | 1 | 0 | 18.8 | src/App.tsx, src/components/TodoCounter.tsx |
| 5 | initial | Pomodoro timer with start, pause and reset | rolled_back | compiler | 13 | 3 | 3 | 33.2 |  |
| 6 | initial | Login and sign-up screen with a toggle between them | committed |  | 6 | 1 | 2 | 21.5 | src/App.tsx, src/components/Login.tsx, src/components/Signup.tsx |
| 7 | initial | Kanban board with 3 columns and buttons to move cards | rolled_back | step_limit | 12 | 0 | 1 | 36.4 |  |
| 8 | initial | Weather card UI with mock data and a Celsius or Fahrenheit toggle | committed |  | 10 | 2 | 1 | 27.7 | src/App.tsx, src/components/WeatherCard.tsx |

5: I could not finish this change cleanly, so I rolled it back. The preview is still the last committed UI. Follow-ups are paused until you retry or start a new UI. TypeScript check failed:
sandbox/.staging/src/App.tsx(4,8): error TS2304: Cannot find name 'PomodoroTimer'.
7: I could not finish this change cleanly, so I rolled it back. The preview is still the last committed UI. Follow-ups are paused until you retry or start a new UI. The step limit was reached.

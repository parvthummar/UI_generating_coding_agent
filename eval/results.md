# Eval results

Recorded run of `python -m scripts.eval` from the `server` folder. The F1 row is the current rollback rule: after prompt 2 fails, that follow-up is refused before any model call.
10 of 12 prompts ended in a clean commit.

| # | Prompt | Build passed | Model calls | Fix attempts | Seconds | Files changed |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Contact form with name, email and message, validation, and a success message | yes | 4 | 2 | 12.8 | src/App.tsx, src/components/ContactForm.tsx |
| 2 | Finance dashboard with summary cards, a bar chart of spending, and a transactions table with mock data | no | 8 | 3 | 25.2 |  |
| 3 | Landing page for a fictional coffee brand with hero, features, pricing and footer | yes | 4 | 0 | 14.7 | src/App.tsx, src/components/Features.tsx, src/components/Footer.tsx, src/components/Hero.tsx, src/components/Pricing.tsx |
| 4 | Todo app with add, complete, delete and filter | yes | 5 | 3 | 15.0 | src/App.tsx, src/components/TodoApp.tsx, src/components/index.ts |
| 5 | Pomodoro timer with start, pause and reset | yes | 3 | 1 | 10.8 | src/App.tsx, src/components/PomodoroTimer.tsx |
| 6 | Login and sign-up screen with a toggle between them | yes | 3 | 1 | 10.6 | src/App.tsx, src/components/AuthToggle.tsx, src/components/Login.tsx, src/components/Signup.tsx |
| 7 | Kanban board with 3 columns and buttons to move cards | yes | 4 | 1 | 12.2 | src/App.tsx, src/components/KanbanBoard.tsx |
| 8 | Weather card UI with mock data and a Celsius or Fahrenheit toggle | yes | 5 | 3 | 10.8 | src/App.tsx, src/components/WeatherCard.tsx, src/components/index.ts |
| F1 | Add a dark mode toggle in the header | no | 0 | 0 | 0.0 |  |
| F2 | Show how many tasks are left | yes | 3 | 0 | 4.7 | src/components/TodoApp.tsx |
| F3 | Change the main color to green and add a testimonials section | yes | 4 | 2 | 7.8 | src/App.tsx, src/components/Hero.tsx, src/components/Testimonials.tsx |
| F4 | Make the message field optional | yes | 2 | 0 | 3.9 | src/components/ContactForm.tsx |

Follow-ups F4, F2, and F3 changed only the files that request needed (`ContactForm.tsx`, `TodoApp.tsx`, and the landing hero plus a new testimonials section).

Prompt 2 used 8 model calls and 3 fix attempts, then rolled back, so nothing was committed. F1 is the dark-mode follow-up in that same session. It is refused (`followup_blocked`) before a model call, so the starter app is not edited and no files change. Rechecked on this build: 0 model calls, 0 fix attempts, files unchanged.

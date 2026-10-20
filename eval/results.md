# Eval results

Real run of `python -m scripts.eval` from the `server` folder.
7 of 12 prompts ended in a clean commit.

| # | Prompt | Build passed | Model calls | Fix attempts | Seconds | Files changed |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Contact form with name, email and message, validation, and a success message | no | 6 | 3 | 24.7 |  |
| 2 | Finance dashboard with summary cards, a bar chart of spending, and a transactions table with mock data | no | 6 | 3 | 32.8 |  |
| 3 | Landing page for a fictional coffee brand with hero, features, pricing and footer | yes | 4 | 0 | 15.4 | src/App.tsx, src/components/Features.tsx, src/components/Footer.tsx, src/components/Hero.tsx, src/components/Pricing.tsx |
| 4 | Todo app with add, complete, delete and filter | yes | 5 | 2 | 15.8 | src/App.tsx, src/components/TodoApp.tsx |
| 5 | Pomodoro timer with start, pause and reset | yes | 5 | 2 | 15.2 | src/App.tsx, src/components/PomodoroTimer.tsx |
| 6 | Login and sign-up screen with a toggle between them | yes | 6 | 2 | 17.1 | src/App.tsx, src/components/AuthToggle.tsx, src/components/Login.tsx, src/components/Signup.tsx |
| 7 | Kanban board with 3 columns and buttons to move cards | yes | 7 | 1 | 19.5 | src/App.tsx, src/components/KanbanBoard.tsx |
| 8 | Weather card UI with mock data and a Celsius or Fahrenheit toggle | yes | 6 | 3 | 16.5 | src/App.tsx, src/components/WeatherCard.tsx |
| F1 | Add a dark mode toggle in the header | no | 0 | 0 | 0.0 |  |
| F2 | Show how many tasks are left | no | 6 | 3 | 14.2 |  |
| F3 | Change the main color to green and add a testimonials section | yes | 4 | 1 | 11.9 | src/App.tsx, src/components/Features.tsx, src/components/Hero.tsx, src/components/Testimonials.tsx |
| F4 | Make the message field optional | no | 0 | 0 | 0.0 |  |

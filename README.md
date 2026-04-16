# Football Training Progress Tracker

Simple Flask web application to log and view football training sessions.

## Features

- Open signup with username and password
- Login page for anyone to create an account and return later
- Leaderboard page showing the strongest training performers
- Add session date, drill, duration, and notes (per user)
- View past sessions in a sortable table
- Uses SQLite for storage, with per-user data isolation
- Modern, world‑class GUI built with Bootstrap 5, gradients, glassmorphism, and smooth Apple‑TV‑inspired visuals
- Dashboard shows total sessions/minutes and a bar chart of drill durations with soft color palette

## Running Locally

1. Create a Python virtual environment and activate it:
   ```sh
   python -m venv venv
   .\\venv\\Scripts\\activate
   ```
2. Install dependencies:
   ```sh
   pip install -r requirements.txt
   ```
3. Start the app:
   ```sh
   python app.py
   ```
4. Open `http://localhost:5000` in your browser. You will first see a login screen where anyone can sign in with a username and password or create a new account.

> **Note:** if you're updating from an earlier version without users, the app may preserve old session rows using the existing `data.db`. To start fresh remove `data.db` and restart.

## Deployment to Render

1. Create a new **Web Service** on Render.
2. Connect it to your GitHub repo containing this project (push it to Git first).
3. Use the following settings:
   - **Environment**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
4. Render will handle the rest and provide a URL where the tracker is live.

> The SQLite database (`data.db`) will be created automatically in the project root when the app runs.

Feel free to customize styles or add charts/analytics! 🎯

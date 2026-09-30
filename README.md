# MSUEdu AI

An AI-assisted student tutoring and peer learning platform (a student project, **not** an official
Mindanao State University website). Built with Flask, MySQL and a local AI model (Ollama).

- **Students:** find approved tutors, request sessions, use an AI assistant, take AI-made quizzes,
  use an AI coordinator that *prepares* bookings for their confirmation, leave feedback, see their progress.
- **Tutors:** set subjects and weekly availability, accept / decline / propose new times, record sessions.
- **Administrators:** review tutors, manage accounts and subjects, monitor requests, moderate feedback,
  view reports and the audit log.

## Requirements
Windows, Python 3.10+, MySQL 8 (with Workbench), VS Code. Ollama with a small model for the AI features.

## First-time setup (PowerShell, in the project folder)
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env       # then edit .env: SECRET_KEY, DB_PASSWORD, OLLAMA_MODEL
```
Generate a secret key: `python -c "import secrets; print(secrets.token_hex(32))"`

Create the database, in MySQL Workbench as `root`, running these files **in order**:
`database/setup_phase1.sql` (change its password first), then `schema_phase2.sql` ... `schema_phase9.sql`.

Then:
```powershell
flask --app run create-admin      # your administrator (asks for a password)
python run.py                     # http://127.0.0.1:5000
```

## Everyday commands
| Command | What it does |
|---|---|
| `python run.py` | Starts the site (and the reminder job). |
| `python -m pytest -v` | Runs all automated tests (no MySQL or Ollama needed). |
| `flask --app run create-admin` | Creates an administrator. |
| `flask --app run send-reminders` | Sends due session reminders once (for Task Scheduler). |
| `flask --app run seed-demo` | Creates FICTIONAL sample accounts and sessions. |
| `flask --app run remove-demo` | Deletes the sample accounts and their data. |

## Folder guide
| Path | Purpose |
|---|---|
| `run.py`, `config.py` | Start the app; read settings from `.env`. |
| `app/routes/` | One file per area of the site (auth, student, tutor, admin, bookings, ...). |
| `app/services/` | Database work and business rules (requests, notifications, agent tools, ...). |
| `app/ai/` | Ollama client, prompts, quiz validation, agent logic. |
| `app/templates/`, `app/static/` | HTML pages, CSS and JavaScript. |
| `database/` | SQL files, one per phase. |
| `tests/` | Automated tests. |
| `docs/demo_script.md` | Presentation walkthrough and pre-demo checklist. |

## How the AI is kept under control
- The AI runs locally. The browser never talks to it, and its address and model name never reach the browser.
- Generated text is labelled as possibly wrong. Chats are not stored; only counts are logged.
- The coordinator uses the AI only to *understand* a message. Tutors, times and statuses come from the
  database, the tools are a fixed list checked for role and arguments, and nothing is created or cancelled
  until the student presses Confirm. It cannot accept requests for tutors.
- Quiz output is validated; unusable output shows an error and saves nothing.

## Security summary
Password hashing, parameterised SQL, CSRF tokens, role checks on every route, lockout after failed logins,
session revocation on password change or deactivation, a strict Content-Security-Policy, request size
limit, audit log, secrets only in `.env`.
Not included: HTTPS (needed for a real deployment: set `SESSION_COOKIE_SECURE=true`), email, multi-factor
login, file uploads.

## Limitations
- Needs a capable enough local model: small models sometimes fail to produce a usable quiz or plan
  (the app then shows a clear error instead of inventing results).
- Reminders run only while the app or the scheduled command is running.
- No email: password recovery is administrator-assisted.
- The coordinator is for students only and handles one message at a time (no memory between messages).
- Do **not** load real student data without permission, a privacy review and proper safeguards.
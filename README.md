# MSUEdu AI (MSUedu_AI)

A hybrid tutoring platform that combines **Generative AI**, **Agentic AI** and **human student tutors**.
It is a student project and **not** an official Mindanao State University website.

Students learn from lessons and an AI tutor, take AI-written quizzes, get rule-based recommendations, and
book human peer tutors for live sessions (video, chat, whiteboard, files). Tutors get an AI helper and
structured session summaries. Administrators manage accounts, the curriculum, moderation and analytics.

## Stack
Python 3.10+ and Flask, MySQL 8 (PyMySQL), vanilla HTML/CSS/JavaScript, Flask-SocketIO and WebRTC for live
sessions, Ollama (local) or any OpenAI-compatible service for the AI, APScheduler for reminders.

## Quick start (Windows, PowerShell, in the project folder)
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env            # then edit .env: SECRET_KEY, DB_PASSWORD, OLLAMA_MODEL
```
1. In MySQL Workbench as `root`, run `database/setup_phase1.sql` (change its password first). It creates the
   empty database and the app's database user.
2. Create every table (safe to run again, skips what exists):
```powershell
   flask --app run init-db
   flask --app run create-admin
   python run.py                       # http://127.0.0.1:5000
```
3. For a demonstration with fictional data: `flask --app run seed-demo`.

## Commands
| Command | Purpose |
|---|---|
| `python run.py` | Development server (with the reminder job). |
| `python -m pytest -v` | Automated tests. They need no MySQL, Ollama or internet. |
| `flask --app run init-db` | Create or update all tables. |
| `flask --app run verify-schema` | List missing tables or columns. |
| `flask --app run check-config` | Review settings before going live. |
| `flask --app run create-admin` | Create an administrator (password is typed hidden). |
| `flask --app run seed-demo` / `remove-demo` | Fictional sample data. |
| `flask --app run send-reminders` | Send due session reminders once. |
| `.\backup-db.ps1` | Back up the database and uploaded files. |

## Where things are
`app/routes` (pages and JSON endpoints) · `app/services` (rules and database work) · `app/ai` (AI client,
prompts, validators, agent logic) · `app/templates` and `app/static` · `database` (SQL, one file per phase) ·
`tests` · `docs` (architecture, security, deployment, defense guide).

## Generative AI versus Agentic AI (short version)
- **Generative AI writes content** and never acts: tutor chat, notes summaries, quizzes, tutor exercises and
  hints, summary drafts. A person or a validator checks the output.
- **Agentic AI decides and acts within limits.** The **tutoring coordinator** uses the model only to understand a
  request, then fixed checked tools find real availability and *prepare* a booking that the student must confirm.
  The **learning agent** reads measured events (quiz scores, lessons) and applies explicit rules to create
  recommendations, with its reasoning saved. Details: `docs/ARCHITECTURE.md`.

## Status of the requirements
| | |
|---|---|
| **Implemented** | Accounts and roles, learning paths, lessons, AI tutor chat (saved), AI quizzes with server-side grading, student learning profile, learning agent with explainable recommendations, tutor directory with photos, booking with conflict prevention and email updates (when SMTP is configured), live sessions (chat, WebRTC video and audio, screen share, whiteboard, files), tutor AI panel, structured session summaries, feedback, notifications and reminders, admin tools, curriculum management, analytics, audit log, security controls (see `docs/SECURITY.md`). |
| **Configuration required** | A MySQL database; an AI provider (Ollama model or an API key); SMTP settings (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`) for booking emails; `MAIL_BASE_URL` for working links in those emails; HTTPS for camera and microphone outside localhost; a TURN relay for some network combinations; a persistent disk for uploads when hosted; one worker process (see `docs/DEPLOYMENT.md`). |
| **Not built / future** | Email-based password-recovery links, multi-factor login, self-service account deletion and data export, recording of sessions, virus scanning of uploads, shared quiz question bank, payments or tutor earnings, mobile apps, running several server processes (needs a message queue), automated browser-to-browser video tests. |

## Limits to know
AI output can be wrong and is labelled as such. Small local models sometimes fail to make a usable quiz or plan;
the app shows an error instead of inventing results. Quiz scores and summaries are never presented as proof of
mastery. **Do not load real student data** without permission, a privacy review and a hardened deployment.
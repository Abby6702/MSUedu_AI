"""Entry point for a production web server. Run with exactly ONE worker process:

    gunicorn -w 1 --threads 100 --timeout 180 --bind 127.0.0.1:8000 wsgi:app

One worker is required because live-session rooms and whiteboards are kept in that process's memory
(Flask-SocketIO also needs it without a message queue). Run more capacity as separate single-worker instances.
Needs 'pip install gunicorn simple-websocket' on a Linux server."""
import os

from run import app                      # builds the app, applies the proxy setting, registers commands
from app.scheduler import start_scheduler

# Reminders run inside the web process. Turn this on for exactly ONE instance.
# (If two instances both run it, the unique key on notifications still prevents duplicate reminders.)
if os.getenv("START_SCHEDULER", "false").lower() == "true":
    start_scheduler(app)
"""Loaded by pytest before any test. It makes the tests independent of your .env,
so they pass whether .env is in development mode or public-demo mode."""
import os

os.environ["SHOW_SYSTEM_STATUS"] = "true"
os.environ["SESSION_COOKIE_SECURE"] = "false"
os.environ["CSP_ENABLED"] = "true"
os.environ["REMINDERS_ENABLED"] = "false"
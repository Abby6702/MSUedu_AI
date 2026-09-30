"""Login lockout. Only FAILED attempts are stored, as keyed hashes, and old rows are
deleted. It fails open: if this table breaks, people can still log in."""
from datetime import timedelta
from flask import current_app
from app.db import execute, query_one
from app.security import digest
from app.timeutil import utcnow

WINDOW_MINUTES = 15
MAX_PER_IDENTITY = 5      # failed tries for one account (or one password-change form)
MAX_PER_IP = 20           # failed tries from one computer
LOCKED_MESSAGE = "Too many failed attempts. Please wait 15 minutes and try again."


def is_locked(identifier, ip):
    try:
        cutoff = utcnow() - timedelta(minutes=WINDOW_MINUTES)
        by_identity = query_one(
            "SELECT COUNT(*) AS n FROM login_attempts WHERE identity_hash = %s AND attempted_at > %s",
            (digest(identifier), cutoff))["n"]
        by_ip = query_one(
            "SELECT COUNT(*) AS n FROM login_attempts WHERE ip_hash = %s AND attempted_at > %s",
            (digest(ip), cutoff))["n"]
        return by_identity >= MAX_PER_IDENTITY or by_ip >= MAX_PER_IP
    except Exception:
        current_app.logger.exception("Login lockout check failed")
        return False


def record_failure(identifier, ip):
    try:
        now = utcnow()
        execute("INSERT INTO login_attempts (identity_hash, ip_hash, attempted_at) VALUES (%s, %s, %s)",
                (digest(identifier), digest(ip), now))
        execute("DELETE FROM login_attempts WHERE attempted_at < %s", (now - timedelta(days=1),))
    except Exception:
        current_app.logger.exception("Could not record a failed login")


def clear(identifier):
    try:
        execute("DELETE FROM login_attempts WHERE identity_hash = %s", (digest(identifier),))
    except Exception:
        current_app.logger.exception("Could not clear failed logins")
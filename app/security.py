"""Small security helpers."""
import hashlib
import hmac
import secrets
from flask import current_app

# No look-alike characters (0/O, 1/l/I), so a temporary password is easy to read out.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def digest(value):
    """A keyed hash (HMAC-SHA256) of a value. The same value always gives the same
    result, but without SECRET_KEY nobody can reverse or guess-check it."""
    key = current_app.config["SECRET_KEY"].encode("utf-8")
    return hmac.new(key, (value or "").lower().encode("utf-8"), hashlib.sha256).hexdigest()


def generate_temp_password(length=12):
    """A random password that always has at least one letter and one number."""
    while True:
        password = "".join(secrets.choice(_ALPHABET) for _ in range(length))
        if any(c.isdigit() for c in password) and any(c.isalpha() for c in password):
            return password
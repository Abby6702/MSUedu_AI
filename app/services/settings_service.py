"""Platform settings an administrator can change. Reads are cached for 30 seconds
so every page does not hit the database."""
import time
from flask import current_app
from app.db import execute, query_all
from app.timeutil import utcnow

DEFAULTS = {"announcement": "", "registration_open": "true"}
TTL_SECONDS = 30
_cache = {"at": None, "values": None}


def clear_cache():
    _cache["at"] = None
    _cache["values"] = None


def get_all():
    now = time.monotonic()
    if _cache["values"] is not None and _cache["at"] is not None and now - _cache["at"] < TTL_SECONDS:
        return dict(_cache["values"])
    values = dict(DEFAULTS)
    try:
        for row in query_all("SELECT setting_key, setting_value FROM platform_settings"):
            if row["setting_key"] in DEFAULTS:
                values[row["setting_key"]] = row["setting_value"]
    except Exception:
        current_app.logger.exception("Could not load platform settings")
        return values                      # not cached, so it recovers as soon as the database does
    _cache["at"], _cache["values"] = now, values
    return dict(values)


def announcement():
    return get_all()["announcement"]


def registration_open():
    return get_all()["registration_open"] == "true"


def save(admin_id, values):
    for key, value in values.items():
        if key not in DEFAULTS:
            continue                        # unknown keys are ignored
        execute(
            "INSERT INTO platform_settings (setting_key, setting_value, updated_by, updated_at) "
            "VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value), "
            "updated_by = VALUES(updated_by), updated_at = VALUES(updated_at)",
            (key, value, admin_id, utcnow()))
    clear_cache()
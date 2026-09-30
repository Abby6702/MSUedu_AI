"""The agent's toolbox. The AI never touches the database directly. It can only
cause these functions to run, and only through run_tool(), which checks the tool
name, the user's role and every argument first."""
import json
from datetime import date, datetime, timedelta

from flask import current_app

from app import validators_request as vr
from app.ai import agent_logic
from app.db import execute, get_connection, query_all, query_one
from app.services import request_service as rs
from app.services import subject_service, tutor_service
from app.timeutil import format_range_local, local_to_utc, utcnow

PROPOSAL_MINUTES = 30
MAX_PREPARED = 10


class ToolError(Exception):
    """A problem with a tool call. The message is always safe to show to a student."""


# ---------- argument validators ----------
def _v_int(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 2_147_483_647:
        raise ToolError("A tool received an invalid id.")
    return value


def _v_choice(*options):
    def check(value):
        if not isinstance(value, (str, int)) or isinstance(value, bool) or value not in options:
            raise ToolError("A tool received an invalid option.")
        return value
    return check


def _v_text(low, high):
    def check(value):
        if not isinstance(value, str):
            raise ToolError("A tool received invalid text.")
        value = " ".join(value.split())
        if not low <= len(value) <= high:
            raise ToolError("A tool received text of the wrong length.")
        return value
    return check


def _v_dates(value):
    if (not isinstance(value, list) or not 1 <= len(value) <= 60
            or not all(isinstance(d, date) and not isinstance(d, datetime) for d in value)):
        raise ToolError("A tool received invalid dates.")
    return value


def _v_datetime(value):
    if not isinstance(value, datetime) or value.tzinfo is not None:
        raise ToolError("A tool received an invalid time.")
    return value


def _v_timedelta(value):
    if not isinstance(value, timedelta):
        raise ToolError("A tool received an invalid time of day.")
    return value


# ---------- logging (numeric ids only, never message text) ----------
def log_step(ctx, step, tool_name, ok, detail=None):
    try:
        execute(
            "INSERT INTO agent_action_logs (run_id, user_id, step, tool_name, ok, detail, "
            "created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (ctx["run_id"], ctx["user_id"], step, tool_name, 1 if ok else 0,
             (detail or "")[:255] or None, utcnow()),
        )
    except Exception:
        current_app.logger.exception("Could not write the agent log")


# ---------- proposals ----------
def _load_payload(value):
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _card(proposal_id, payload):
    return {"id": proposal_id, "title": payload["title"], "lines": payload["lines"],
            "expires_minutes": PROPOSAL_MINUTES}


def _store_proposal(user_id, kind, data, title, lines):
    """Save a prepared proposal (or return the identical one that already exists)."""
    now = utcnow()
    execute("UPDATE agent_proposals SET status = 'expired', resolved_at = %s "
            "WHERE user_id = %s AND status = 'prepared' AND expires_at < %s",
            (now, user_id, now))
    rows = query_all("SELECT id, kind, payload FROM agent_proposals "
                     "WHERE user_id = %s AND status = 'prepared'", (user_id,))
    for row in rows:                                     # avoid duplicate proposals
        existing = _load_payload(row["payload"])
        if row["kind"] == kind and existing and existing.get("data") == data:
            return {"ok": True, "proposal": _card(row["id"], existing)}
    if len(rows) >= MAX_PREPARED:
        return {"ok": False, "problem": "You have several unconfirmed proposals. "
                                        "Confirm or discard some of them first."}
    payload = {"data": data, "title": title, "lines": lines}
    new_id = execute(
        "INSERT INTO agent_proposals (user_id, kind, payload, status, created_at, expires_at) "
        "VALUES (%s, %s, %s, 'prepared', %s, %s)",
        (user_id, kind, json.dumps(payload, ensure_ascii=False), now,
         now + timedelta(minutes=PROPOSAL_MINUTES)),
    )
    return {"ok": True, "proposal": _card(new_id, payload)}


def load_proposal(proposal_id, user_id):
    """Only the proposal's owner can load it."""
    row = query_one("SELECT id, kind, payload, status, expires_at FROM agent_proposals "
                    "WHERE id = %s AND user_id = %s", (proposal_id, user_id))
    if row is None:
        return None
    row["payload"] = _load_payload(row["payload"])
    return row


def _update_status(proposal_id, user_id, new_status, from_status=None, unexpired_only=False):
    now = utcnow()
    sql = "UPDATE agent_proposals SET status = %s, resolved_at = %s WHERE id = %s AND user_id = %s"
    params = [new_status, None if new_status == "prepared" else now, proposal_id, user_id]
    if from_status:
        sql += " AND status = %s"
        params.append(from_status)
    if unexpired_only:
        sql += " AND expires_at >= %s"
        params.append(now)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            changed = cur.execute(sql, params)
        conn.commit()
        return changed
    finally:
        conn.close()


def claim_proposal(proposal_id, user_id):
    """Atomically move prepared -> confirmed. Only ONE caller can win, so a
    double-click can never send two requests."""
    return _update_status(proposal_id, user_id, "confirmed", "prepared", True) == 1


def discard_proposal(proposal_id, user_id):
    return _update_status(proposal_id, user_id, "discarded", "prepared") == 1


def set_status(proposal_id, user_id, new_status):
    return _update_status(proposal_id, user_id, new_status)


# ---------- the tools ----------
def _t_list_subjects(user_id):
    return subject_service.list_subjects()


def _t_find_tutors(user_id, subject_id, format=""):
    return tutor_service.find_matches(subject_id, {"day": None, "time": None, "format": format})


def _t_get_open_slots(user_id, tutor_id, dates, duration, time_pref=None, part_of_day=""):
    tutor = tutor_service.get_public_tutor(tutor_id)     # approved and active only
    if tutor is None:
        raise ToolError("That tutor is not available.")
    window_start = local_to_utc(min(dates).isoformat(), "00:00")
    window_end = local_to_utc((max(dates) + timedelta(days=1)).isoformat(), "00:00")
    rows = query_all(
        "SELECT start_at, end_at FROM tutoring_requests WHERE status = 'accepted' "
        "AND (tutor_id = %s OR student_id = %s) AND end_at > %s AND start_at < %s",
        (tutor_id, user_id, window_start, window_end),
    )
    busy = [(r["start_at"], r["end_at"]) for r in rows]
    slots = agent_logic.compute_open_slots(tutor["availability"], busy, dates, duration,
                                           utcnow(), time_pref, part_of_day, limit=4)
    for s in slots:
        s["label"] = format_range_local(s["start"], s["end"])
        s["start_iso"] = s["start"].isoformat()
    return slots


def _t_get_my_requests(user_id):
    return rs.grouped_requests(user_id, "student")


def _t_prepare_request(user_id, tutor_id, subject_id, topic, format, start, duration):
    """Runs every real check in DRY-RUN mode, then saves a proposal. Sends nothing."""
    now = utcnow()
    if start < now + vr.MIN_LEAD:
        return {"ok": False, "problem": "That time is too soon. Choose a time at least 1 hour ahead."}
    if start > now + vr.MAX_AHEAD:
        return {"ok": False, "problem": "That time is more than 60 days ahead."}
    subject = next((o for o in rs.tutor_subject_options(tutor_id) if o["id"] == subject_id), None)
    tutor = tutor_service.get_public_tutor(tutor_id)
    if subject is None or tutor is None:
        return {"ok": False, "problem": "That tutor does not teach this subject or is not available."}

    end = start + timedelta(minutes=duration)
    data = {"subject_id": subject_id, "topic": topic, "description": "", "format": format,
            "start": start, "end": end}
    _new_id, problem = rs.create_request(user_id, tutor_id, data, dry_run=True)
    if problem:
        return {"ok": False, "problem": problem}

    stored = {"tutor_id": tutor_id, "subject_id": subject_id, "topic": topic, "format": format,
              "start": start.isoformat(), "end": end.isoformat()}
    lines = [f"Tutor: {tutor['full_name']}", f"Subject: {subject['name']}", f"Topic: {topic}",
             f"When: {format_range_local(start, end)}",
             f"Format: {tutor_service.FORMAT_LABELS[format]}"]
    return _store_proposal(user_id, "request", stored, "Tutoring request ready to send", lines)


def _t_prepare_cancel(user_id, request_id):
    req = rs.get_for_user(request_id, user_id)
    if req is None or req["student_id"] != user_id:
        return {"ok": False, "problem": "I could not find that request."}
    if "cancel" not in rs.available_actions(req, "student"):
        return {"ok": False, "problem": "That request cannot be cancelled right now."}
    lines = [f"Session: {req['subject_name']}: {req['topic']}", f"Tutor: {req['tutor_name']}",
             f"When: {format_range_local(req['start_at'], req['end_at'])}",
             "This cannot be undone."]
    return _store_proposal(user_id, "cancel", {"request_id": request_id},
                           "Cancellation ready to confirm", lines)


# name -> what it may do. "args": {name: (validator, required)}
TOOLS = {
    "list_subjects": {
        "label": "Looked up the active subjects", "roles": ("student",),
        "args": {}, "fn": _t_list_subjects},
    "find_tutors": {
        "label": "Searched approved tutors for the subject", "roles": ("student",),
        "args": {"subject_id": (_v_int, True), "format": (_v_choice("online", "in_person", ""), False)},
        "fn": _t_find_tutors},
    "get_open_slots": {
        "label": "Checked a tutor's real open times", "roles": ("student",),
        "args": {"tutor_id": (_v_int, True), "dates": (_v_dates, True),
                 "duration": (_v_choice(*vr.DURATIONS), True),
                 "time_pref": (_v_timedelta, False),
                 "part_of_day": (_v_choice("morning", "afternoon", "evening", ""), False)},
        "fn": _t_get_open_slots},
    "get_my_requests": {
        "label": "Read your requests and sessions", "roles": ("student",),
        "args": {}, "fn": _t_get_my_requests},
    "prepare_request": {
        "label": "Prepared a request for your confirmation (nothing sent)", "roles": ("student",),
        "args": {"tutor_id": (_v_int, True), "subject_id": (_v_int, True),
                 "topic": (_v_text(2, 150), True), "format": (_v_choice("online", "in_person"), True),
                 "start": (_v_datetime, True), "duration": (_v_choice(*vr.DURATIONS), True)},
        "fn": _t_prepare_request},
    "prepare_cancel": {
        "label": "Prepared a cancellation for your confirmation (nothing cancelled)",
        "roles": ("student",),
        "args": {"request_id": (_v_int, True)}, "fn": _t_prepare_cancel},
}


def run_tool(ctx, name, **args):
    """The ONLY way the agent runs a tool. ctx = {user_id, role, run_id, steps}."""
    tool = TOOLS.get(name)
    if tool is None:
        raise ToolError("Unknown tool.")
    if ctx.get("role") not in tool["roles"]:
        log_step(ctx, "tool", name, False, "role_not_allowed")
        raise ToolError("You are not allowed to use that tool.")
    if set(args) - set(tool["args"]):
        raise ToolError("A tool received unexpected arguments.")

    clean = {}
    for key, (validator, required) in tool["args"].items():
        if args.get(key) is None:
            if required:
                raise ToolError("A tool is missing a required value.")
            continue
        clean[key] = validator(args[key])

    detail = " ".join(f"{k}={v}" for k, v in clean.items()
                      if isinstance(v, int) and not isinstance(v, bool))   # ids only
    try:
        result = tool["fn"](ctx["user_id"], **clean)      # user id comes from the session
    except ToolError:
        log_step(ctx, "tool", name, False, detail)
        raise
    except Exception:
        current_app.logger.exception("Agent tool %s failed", name)
        log_step(ctx, "tool", name, False, detail)
        raise ToolError("A tool could not finish.")

    log_step(ctx, "tool", name, True, detail)
    text = tool["label"] + (f" ({len(result)} found)" if isinstance(result, list) else "")
    ctx["steps"].append({"kind": "tool", "text": text})
    return result
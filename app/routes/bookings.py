"""Tutoring requests: create, list, confirm actions, propose a new time."""
from flask import (Blueprint, abort, current_app, flash, g, redirect,
                   render_template, request, url_for)
from app import validators_request as vr
from app.auth_utils import role_required
from app.services import request_service as rs
from app.services import tutor_service as tutors
from app.timeutil import format_local, format_range_local, to_local, utcnow
from app.validators import clean

bookings_bp = Blueprint("bookings", __name__)

EMPTY_GROUPS = {"attention": [], "upcoming": [], "history": []}

ACTIONS = {
    "accept": {"title": "Accept this request?", "button": "Yes, accept",
               "text": "This confirms the session. It will appear under upcoming sessions for both of you.",
               "danger": False},
    "decline": {"title": "Decline this request?", "button": "Yes, decline",
                "text": "The student will see that you declined. You may add a short reason.",
                "danger": True},
    "cancel": {"title": "Cancel this?", "button": "Yes, cancel it",
               "text": "This cannot be undone.", "danger": True},
    "complete": {"title": "Mark this session as completed?", "button": "Yes, mark completed",
                 "text": "Only do this if the session took place.", "danger": False},
    "accept_proposal": {"title": "Accept the new time?", "button": "Yes, accept new time",
                        "text": "This confirms the session at the tutor's proposed time.",
                        "danger": False},
}


@bookings_bp.app_template_filter("local_dt")
def local_dt_filter(value):
    return format_local(value)


@bookings_bp.app_template_filter("local_range")
def local_range_filter(start, end):
    return format_range_local(start, end)


def _back_url(role):
    return url_for("bookings.my_requests" if role == "student" else "bookings.tutor_requests")


def _date_limits():
    today = to_local(utcnow()).date()
    return today.isoformat(), (today.replace(year=today.year + 1)).isoformat()


# ---------- student: create a request ----------
@bookings_bp.route("/student/tutors/<int:tutor_id>/request", methods=["GET", "POST"])
@role_required("student")
def new_request(tutor_id):
    tutor = tutors.get_public_tutor(tutor_id)
    if tutor is None:
        abort(404)
    options = rs.tutor_subject_options(tutor_id)
    valid_ids = {o["id"] for o in options}
    errors, data, review, subject_name = [], {}, False, ""

    if request.method == "POST":
        data, errors = vr.validate_request_form(request.form, valid_ids)
        step = request.form.get("step")
        if step == "edit":                    # "Change details" button on the review page
            data, errors = request.form, []
        elif not errors:
            try:
                new_id, problem = rs.create_request(
                    g.user["id"], tutor_id, data, dry_run=(step != "confirm"))
            except Exception:
                current_app.logger.exception("Creating request failed")
                problem = "Something went wrong. Please try again."
            if problem:
                errors.append(problem)
            elif step == "confirm":
                flash("Request sent. The tutor will reply soon.", "success")
                return redirect(url_for("bookings.my_requests"))
            else:
                review = True
                subject_name = next((o["name"] for o in options
                                     if o["id"] == data["subject_id"]), "")

    min_date, max_date = _date_limits()
    return render_template("student/request_form.html", tutor=tutor, options=options,
                           data=data, errors=errors, review=review, subject_name=subject_name,
                           durations=vr.DURATIONS, min_date=min_date, max_date=max_date,
                           format_labels=tutors.FORMAT_LABELS)


# ---------- lists ----------
def _list_page(role, title):
    groups, error = EMPTY_GROUPS, None
    try:
        groups = rs.grouped_requests(g.user["id"], role)
    except Exception:
        current_app.logger.exception("Loading requests failed")
        error = "Could not load your requests. Please try again."
    return render_template("bookings/list.html", groups=groups, viewer=role,
                           title=title, error=error)


@bookings_bp.route("/student/requests")
@role_required("student")
def my_requests():
    return _list_page("student", "My tutoring requests")


@bookings_bp.route("/tutor/requests")
@role_required("tutor")
def tutor_requests():
    return _list_page("tutor", "Tutoring requests")


# ---------- confirm-then-act ----------
@bookings_bp.route(
    "/requests/<int:request_id>/<any(accept,decline,cancel,complete,accept_proposal):action>",
    methods=["GET", "POST"])
@role_required("student", "tutor")
def act(request_id, action):
    role = g.user["role"]
    req = rs.get_for_user(request_id, g.user["id"])
    if req is None:
        abort(404)      # not yours, or it does not exist
    if action not in rs.available_actions(req, role):
        flash("That action is not possible for this request right now.", "error")
        return redirect(_back_url(role))

    if request.method == "POST":
        note = clean(request.form.get("note"))[:500] if action == "decline" else None
        try:
            ok, message = rs.perform_action(request_id, g.user["id"], action, note)
        except Exception:
            current_app.logger.exception("Request action failed")
            ok, message = False, "Something went wrong. Please try again."
        flash(message, "success" if ok else "error")
        return redirect(_back_url(role))

    return render_template("bookings/confirm.html", req=req, action=action,
                           info=ACTIONS[action], back_url=_back_url(role))


# ---------- tutor proposes another time ----------
@bookings_bp.route("/tutor/requests/<int:request_id>/propose", methods=["GET", "POST"])
@role_required("tutor")
def propose(request_id):
    req = rs.get_for_user(request_id, g.user["id"])
    if req is None:
        abort(404)
    if "propose" not in rs.available_actions(req, "tutor"):
        flash("You can only propose a new time for a pending request.", "error")
        return redirect(url_for("bookings.tutor_requests"))

    errors, data = [], {}
    if request.method == "POST":
        data = request.form
        start, end, _duration, errors = vr.validate_when(request.form)
        if not errors:
            note = clean(request.form.get("note"))[:500]
            try:
                ok, message = rs.propose_time(request_id, g.user["id"], start, end, note)
            except Exception:
                current_app.logger.exception("Proposing a time failed")
                ok, message = False, "Something went wrong. Please try again."
            if ok:
                flash(message, "success")
                return redirect(url_for("bookings.tutor_requests"))
            errors.append(message)

    min_date, max_date = _date_limits()
    return render_template("tutor/propose.html", req=req, errors=errors, data=data,
                           durations=vr.DURATIONS, min_date=min_date, max_date=max_date)
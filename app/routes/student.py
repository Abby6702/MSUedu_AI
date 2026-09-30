from flask import Blueprint, abort, current_app, flash, g, render_template, request
from app import validators_tutor as vt
from app.auth_utils import role_required
from app.services import progress_service as ps
from app.services import quiz_service
from app.services import request_service as rs
from app.services import subject_service, tutor_service as tutors
from app.services import user_service as users

student_bp = Blueprint("student", __name__, url_prefix="/student")


@student_bp.route("/dashboard")
@role_required("student")
def dashboard():
    profile = users.get_profile(g.user["id"], "student") or {}
    suggested, upcoming, pending, activity = [], [], [], []
    try:
        suggested = subject_service.list_subjects()[:6]
        groups = rs.grouped_requests(g.user["id"], "student")
        upcoming, pending = groups["upcoming"][:3], groups["attention"][:3]
        activity = quiz_service.recent_attempts(g.user["id"], 3)
    except Exception:
        current_app.logger.exception("Could not load dashboard data")
    return render_template("student/dashboard.html", profile=profile, suggested=suggested,
                           upcoming=upcoming, pending=pending, activity=activity)


@student_bp.route("/tutors")
@role_required("student")
def find_tutors():
    filters = vt.parse_search_args(request.args)
    results, error = [], None
    try:
        results = tutors.search_tutors(filters)
        subjects = subject_service.list_subjects()
    except Exception:
        current_app.logger.exception("Tutor search failed")
        subjects, error = [], "Search is temporarily unavailable. Please try again."
    return render_template("student/find_tutors.html", filters=filters, results=results,
                           subjects=subjects, day_names=vt.DAY_NAMES, error=error)


@student_bp.route("/tutors/<int:tutor_id>")
@role_required("student")
def tutor_detail(tutor_id):
    tutor = tutors.get_public_tutor(tutor_id)
    if tutor is None:
        abort(404)      # hidden, unapproved or inactive tutors look like they don't exist
    rating, feedback_items = {"n": 0, "avg": None}, []
    try:
        rating = ps.rating_summary(tutor_id)
        feedback_items = ps.tutor_feedback(tutor_id, 5)     # anonymous, visible feedback only
    except Exception:
        current_app.logger.exception("Could not load tutor feedback")
    return render_template("student/tutor_detail.html", tutor=tutor,
                           format_labels=tutors.FORMAT_LABELS,
                           rating=rating, feedback_items=feedback_items)


@student_bp.route("/match")
@role_required("student")
def match():
    subjects = subject_service.list_subjects()
    valid_ids = {s["id"] for s in subjects}
    args = request.args
    errors, results, searched = [], [], False

    subject_id = int(args["subject_id"]) if args.get("subject_id", "").isdigit() else None
    day = int(args["day"]) if args.get("day", "").isdigit() and int(args["day"]) <= 6 else None
    fmt = args.get("format", "")
    fmt = fmt if fmt in ("online", "in_person") else ""
    time_text = (args.get("time") or "").strip()
    want_time = vt.parse_hhmm(time_text) if time_text else None

    if "subject_id" in args:
        searched = True
        if subject_id not in valid_ids:
            errors.append("Please choose a subject.")
        if time_text and want_time is None:
            errors.append("Enter a valid preferred time.")
        if time_text and day is None and want_time is not None:
            errors.append("Choose a day if you want to match a preferred time.")
        if not errors:
            try:
                criteria = {"day": day, "time": want_time, "format": fmt}
                results = tutors.find_matches(subject_id, criteria)
            except Exception:
                current_app.logger.exception("Matching failed")
                errors.append("Matching is temporarily unavailable. Please try again.")

    return render_template("student/match.html", subjects=subjects, day_names=vt.DAY_NAMES,
                           results=results, errors=errors, searched=searched,
                           sel={"subject_id": subject_id, "day": day, "format": fmt,
                                "time": time_text},
                           format_labels=tutors.FORMAT_LABELS)
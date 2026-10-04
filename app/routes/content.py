"""Administrator content management: topics and lessons (the learning paths), and the quiz overview."""
from flask import (Blueprint, abort, current_app, flash, g, redirect,
                   render_template, request, url_for)
from app import validators_curriculum as vc
from app.auth_utils import role_required
from app.services import analytics_service, curriculum_service as cs
from app.services import user_service as users

content_bp = Blueprint("content", __name__, url_prefix="/admin")


def _audit(action, target_type, target_id, details=None):
    """The change is already done, so an audit failure is logged instead of hiding the success."""
    try:
        users.log_audit(g.user["id"], action, target_type, target_id, (details or "")[:200] or None)
    except Exception:
        current_app.logger.exception("Could not write the audit log")


# ---------- subjects ----------
@content_bp.route("/curriculum")
@role_required("admin")
def index():
    rows, error = [], None
    try:
        rows = cs.list_subjects()
    except Exception:
        current_app.logger.exception("Could not list subjects for the curriculum")
        error = "Could not load the subjects. Please try again."
    return render_template("content/curriculum.html", rows=rows, error=error)


@content_bp.route("/curriculum/<int:subject_id>")
@role_required("admin")
def subject(subject_id):
    subj = cs.get_subject(subject_id)
    if subj is None:
        abort(404)
    levels, error = [], None
    try:
        levels = cs.subject_tree(subject_id)
    except Exception:
        current_app.logger.exception("Could not load a subject's curriculum")
        error = "Could not load the topics. Please try again."
    return render_template("content/subject.html", subject=subj, levels=levels, error=error)


# ---------- topics ----------
@content_bp.route("/curriculum/<int:subject_id>/topics/new", methods=["GET", "POST"])
@role_required("admin")
def new_topic(subject_id):
    subj = cs.get_subject(subject_id)
    if subj is None:
        abort(404)
    errors, data = [], {"name": "", "level": 1, "position": None}
    if request.method == "POST":
        data, errors = vc.validate_topic(request.form)
        if not errors:
            try:
                topic_id = cs.create_topic(subject_id, data)
            except cs.TopicExists:
                errors.append("This subject already has a topic with that name.")
            except Exception:
                current_app.logger.exception("Creating a topic failed")
                errors.append("Could not save the topic. Please try again.")
            else:
                _audit("topic_created", "topic", topic_id, f"{subj['name']}: {data['name']}")
                flash("Topic added. Now add its lessons.", "success")
                return redirect(url_for("content.subject", subject_id=subject_id))
    return render_template("content/topic_form.html", subject=subj, topic=None, data=data, errors=errors)


@content_bp.route("/curriculum/topics/<int:topic_id>/edit", methods=["GET", "POST"])
@role_required("admin")
def edit_topic(topic_id):
    topic = cs.get_topic(topic_id)
    if topic is None:
        abort(404)
    errors = []
    data = {"name": topic["name"], "level": topic["level"], "position": topic["position"]}
    if request.method == "POST":
        data, errors = vc.validate_topic(request.form)
        if not errors:
            final = dict(data, position=data["position"] or topic["position"])
            try:
                cs.update_topic(topic_id, final)
            except cs.TopicExists:
                errors.append("This subject already has a topic with that name.")
            except Exception:
                current_app.logger.exception("Updating a topic failed")
                errors.append("Could not save the topic. Please try again.")
            else:
                _audit("topic_updated", "topic", topic_id, f"{topic['subject_name']}: {final['name']}")
                flash("Topic saved.", "success")
                return redirect(url_for("content.subject", subject_id=topic["subject_id"]))
    subj = {"id": topic["subject_id"], "name": topic["subject_name"]}
    return render_template("content/topic_form.html", subject=subj, topic=topic, data=data, errors=errors)


@content_bp.route("/curriculum/topics/<int:topic_id>/toggle", methods=["POST"])
@role_required("admin")
def toggle_topic(topic_id):
    topic = cs.get_topic(topic_id)
    if topic is None:
        abort(404)
    show = not topic["is_active"]
    try:
        cs.set_topic_active(topic_id, show)
    except Exception:
        current_app.logger.exception("Changing a topic's visibility failed")
        flash("Something went wrong. Nothing was changed.", "error")
    else:
        _audit("topic_shown" if show else "topic_hidden", "topic", topic_id, topic["name"])
        flash("Topic is visible to students again." if show
              else "Topic hidden. Its lessons are hidden from students too. Progress is kept.", "success")
    return redirect(url_for("content.subject", subject_id=topic["subject_id"]))


# ---------- lessons ----------
@content_bp.route("/curriculum/topics/<int:topic_id>/lessons/new", methods=["GET", "POST"])
@role_required("admin")
def new_lesson(topic_id):
    topic = cs.get_topic(topic_id)
    if topic is None:
        abort(404)
    errors, data = [], {"title": "", "body": "", "difficulty": "easy", "minutes": 5}
    if request.method == "POST":
        data, errors = vc.validate_lesson(request.form)
        if not errors:
            try:
                lesson_id = cs.create_lesson(topic_id, data)
            except cs.LessonExists:
                errors.append("This topic already has a lesson with that title.")
            except Exception:
                current_app.logger.exception("Creating a lesson failed")
                errors.append("Could not save the lesson. Please try again.")
            else:
                _audit("lesson_created", "lesson", lesson_id, f"{topic['name']}: {data['title']}")
                flash("Lesson added. Students can read it now.", "success")
                return redirect(url_for("content.subject", subject_id=topic["subject_id"]))
    return render_template("content/lesson_form.html", topic=topic, lesson=None, data=data, errors=errors)


@content_bp.route("/curriculum/lessons/<int:lesson_id>/edit", methods=["GET", "POST"])
@role_required("admin")
def edit_lesson(lesson_id):
    lesson = cs.get_lesson(lesson_id)
    if lesson is None:
        abort(404)
    errors = []
    data = {k: lesson[k] for k in ("title", "body", "difficulty", "minutes")}
    if request.method == "POST":
        data, errors = vc.validate_lesson(request.form)
        if not errors:
            try:
                cs.update_lesson(lesson_id, data)
            except cs.LessonExists:
                errors.append("This topic already has a lesson with that title.")
            except Exception:
                current_app.logger.exception("Updating a lesson failed")
                errors.append("Could not save the lesson. Please try again.")
            else:
                _audit("lesson_updated", "lesson", lesson_id, f"{lesson['topic_name']}: {data['title']}")
                flash("Lesson saved.", "success")
                return redirect(url_for("content.subject", subject_id=lesson["subject_id"]))
    topic = {"id": lesson["topic_id"], "name": lesson["topic_name"], "subject_id": lesson["subject_id"],
             "subject_name": lesson["subject_name"]}
    return render_template("content/lesson_form.html", topic=topic, lesson=lesson, data=data, errors=errors)


@content_bp.route("/curriculum/lessons/<int:lesson_id>/toggle", methods=["POST"])
@role_required("admin")
def toggle_lesson(lesson_id):
    lesson = cs.get_lesson(lesson_id)
    if lesson is None:
        abort(404)
    show = not lesson["is_active"]
    try:
        cs.set_lesson_active(lesson_id, show)
    except Exception:
        current_app.logger.exception("Changing a lesson's visibility failed")
        flash("Something went wrong. Nothing was changed.", "error")
    else:
        _audit("lesson_shown" if show else "lesson_hidden", "lesson", lesson_id, lesson["title"])
        flash("Lesson is visible to students again." if show
              else "Lesson hidden from students. Progress is kept.", "success")
    return redirect(url_for("content.subject", subject_id=lesson["subject_id"]))


# ---------- quiz overview ----------
@content_bp.route("/quizzes")
@role_required("admin")
def quizzes():
    data, error = None, None
    try:
        data = analytics_service.quiz_overview()
    except Exception:
        current_app.logger.exception("Could not build the quiz overview")
        error = "Could not load the quiz overview. Please try again."
    return render_template("content/quizzes.html", d=data, error=error)
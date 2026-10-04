"""The student learning profile, built ONLY from stored events: quiz attempts,
completed lessons, completed sessions. AI conversation content is never used."""
from app.db import query_all, query_one
from flask import current_app

from app.services import learning_service, progress_service, summary_service

STRONG_MIN = 75     # average AND latest score at or above this = strong
WEAK_MAX = 60       # average OR latest score below this = weak
TREND_STEP = 10     # a change of this many points between the last two quizzes


# ---------- rules (no database, easy to test) ----------
def pct(score, total):
    return round(100 * score / total) if total else 0


def classify(average, latest):
    if average >= STRONG_MIN and latest >= STRONG_MIN:
        return "strong"
    if average < WEAK_MAX or latest < WEAK_MAX:
        return "weak"
    return "developing"


def trend(percents):
    if len(percents) < 2:
        return "new"
    change = percents[-1] - percents[-2]
    if change >= TREND_STEP:
        return "improving"
    if change <= -TREND_STEP:
        return "declining"
    return "steady"


def summarize_topics(rows):
    """rows: one row per quiz attempt, oldest first. Returns one summary per topic,
    weakest first."""
    topics, order = {}, []
    for r in rows:
        t = topics.get(r["topic_id"])
        if t is None:
            t = {"topic_id": r["topic_id"], "topic_name": r["topic_name"],
                 "subject_id": r["subject_id"], "subject_name": r["subject_name"], "percents": []}
            topics[r["topic_id"]] = t
            order.append(t)
        t["percents"].append(pct(r["score"], r["total"]))
    for t in order:
        p = t["percents"]
        t["attempts"] = len(p)
        t["average"] = round(sum(p) / len(p))
        t["latest"] = p[-1]
        t["trend"] = trend(p)
        t["status"] = classify(t["average"], t["latest"])
    return sorted(order, key=lambda t: (t["average"], t["topic_name"]))


# ---------- reading ----------
def topic_attempt_rows(user_id):
    return query_all(
        "SELECT z.topic_id, t.name AS topic_name, t.subject_id, s.name AS subject_name, "
        "a.score, a.total FROM quiz_attempts a JOIN quizzes z ON z.id = a.quiz_id "
        "JOIN topics t ON t.id = z.topic_id JOIN subjects s ON s.id = t.subject_id "
        "WHERE a.user_id = %s ORDER BY a.submitted_at, a.id", (user_id,))

def _tutor_summaries(user_id):
       """Summaries tutors chose to share. A failure here must not break the whole profile."""
       try:
           return summary_service.student_summaries(user_id, 5)
       except Exception:
           current_app.logger.exception("Could not load shared session summaries")
           return []
       
def build_profile(user_id):
    topics = summarize_topics(topic_attempt_rows(user_id))
    quiz = query_one("SELECT COUNT(*) AS n, AVG(100 * score / total) AS avg FROM quiz_attempts "
                     "WHERE user_id = %s AND total > 0", (user_id,))
    subjects = learning_service.list_learning_subjects(user_id)
    done, total = sum(s["done"] for s in subjects), sum(s["total"] for s in subjects)
    minutes = query_one("SELECT COALESCE(SUM(l.minutes), 0) AS m FROM lesson_progress lp "
                        "JOIN lessons l ON l.id = lp.lesson_id WHERE lp.user_id = %s", (user_id,))["m"]
    sessions = query_one("SELECT COUNT(*) AS n FROM tutoring_requests "
                         "WHERE student_id = %s AND status = 'completed'", (user_id,))["n"]
    stats = learning_service.overall_stats(user_id)
    return {
        "lessons_done": done, "lessons_total": total,
        "progress_percent": learning_service.percent(done, total),
        "streak": stats["streak"], "study_minutes": int(minutes),
        "quiz_attempts": quiz["n"],
        "quiz_average": round(float(quiz["avg"])) if quiz["n"] and quiz["avg"] is not None else None,
        "sessions_completed": sessions,
        "ai_questions": progress_service.activity_counts(user_id).get("chat", 0),
        "strong": [t for t in topics if t["status"] == "strong"],
        "developing": [t for t in topics if t["status"] == "developing"],
        "weak": [t for t in topics if t["status"] == "weak"],
        "topics": topics,
        "tutor_summaries": _tutor_summaries(user_id),
    }
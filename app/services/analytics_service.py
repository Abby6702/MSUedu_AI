"""Numbers and chart data for the administrator dashboard and the quiz overview.
Aggregates only: no names, chats or answers are ever selected here."""
from datetime import timedelta

from app.db import query_all, query_one
from app.services import chart_logic
from app.timeutil import to_local, utcnow

DAYS = 14
MAX_ROWS = 50000
DIFFICULTY_ORDER = {"easy": 0, "medium": 1, "hard": 2}

# name shown, css class (colour and line style), query for the timestamps of that activity
ACTIVITY = [
    ("Tutoring requests", "s1", "SELECT created_at AS t FROM tutoring_requests WHERE created_at > %s LIMIT %s"),
    ("Quiz attempts", "s2", "SELECT submitted_at AS t FROM quiz_attempts WHERE submitted_at > %s LIMIT %s"),
    ("Lessons completed", "s3", "SELECT completed_at AS t FROM lesson_progress WHERE completed_at > %s LIMIT %s"),
    ("AI requests", "s4", "SELECT created_at AS t FROM ai_usage_logs WHERE created_at > %s LIMIT %s"),
]


def pct(value):
    return round(float(value)) if value is not None else None


def percent(part, whole):
    return round(100 * part / whole) if whole else None


def activity(days=DAYS):
    """Counts per day for the line chart, plus the same numbers as a table."""
    now = utcnow()
    today = to_local(now).date()
    since = now - timedelta(days=days + 1)          # a little extra, so no local day is cut short
    series = []
    for name, css, sql in ACTIVITY:
        times = [row["t"] for row in query_all(sql, (since, MAX_ROWS))]
        series.append((name, css, chart_logic.bucket_by_day(times, today, days)))
    day_dates = chart_logic.day_list(today, days)
    return {"days": days, "chart": chart_logic.line_chart(day_dates, series),
            "names": [(name, css) for name, css, _c in series],
            "table": [{"day": d.strftime("%d %b"), "values": [counts[i] for _n, _c, counts in series]}
                      for i, d in enumerate(day_dates)]}


def subject_charts():
    requests = [(r["name"], r["n"]) for r in query_all(
        "SELECT s.name, COUNT(*) AS n FROM tutoring_requests r JOIN subjects s ON s.id = r.subject_id "
        "GROUP BY s.id, s.name ORDER BY n DESC, s.name LIMIT 6")]
    lessons = [(r["name"], r["n"]) for r in query_all(
        "SELECT s.name, COUNT(*) AS n FROM lesson_progress lp JOIN lessons l ON l.id = lp.lesson_id "
        "JOIN topics t ON t.id = l.topic_id JOIN subjects s ON s.id = t.subject_id "
        "GROUP BY s.id, s.name ORDER BY n DESC, s.name LIMIT 6")]
    return {"requests": chart_logic.horizontal_bars(requests), "requests_rows": requests,
            "lessons": chart_logic.horizontal_bars(lessons), "lessons_rows": lessons}


def quiz_overview():
    totals = query_one(
        "SELECT (SELECT COUNT(*) FROM quizzes) AS quizzes, "
        "(SELECT COUNT(*) FROM quizzes WHERE topic_id IS NOT NULL) AS linked, "
        "(SELECT COUNT(*) FROM quiz_attempts) AS attempts, "
        "(SELECT COUNT(DISTINCT user_id) FROM quiz_attempts) AS students, "
        "(SELECT AVG(100 * score / total) FROM quiz_attempts WHERE total > 0) AS average")
    by_difficulty = sorted(
        ({"difficulty": r["difficulty"], "attempts": r["attempts"], "average": pct(r["average"])}
         for r in query_all(
             "SELECT z.difficulty, COUNT(*) AS attempts, AVG(100 * a.score / a.total) AS average "
             "FROM quiz_attempts a JOIN quizzes z ON z.id = a.quiz_id WHERE a.total > 0 "
             "GROUP BY z.difficulty")),
        key=lambda r: DIFFICULTY_ORDER.get(r["difficulty"], 9))
    by_subject = [{"name": r["name"], "attempts": r["attempts"], "average": pct(r["average"])}
                  for r in query_all(
                      "SELECT COALESCE(s.name, '(subject removed)') AS name, COUNT(*) AS attempts, "
                      "AVG(100 * a.score / a.total) AS average FROM quiz_attempts a "
                      "JOIN quizzes z ON z.id = a.quiz_id LEFT JOIN subjects s ON s.id = z.subject_id "
                      "WHERE a.total > 0 GROUP BY s.id, s.name ORDER BY attempts DESC, name LIMIT 8")]
    hardest = [{"topic": r["topic"], "subject": r["subject"], "attempts": r["attempts"],
                "average": pct(r["average"])}
               for r in query_all(
                   "SELECT t.name AS topic, s.name AS subject, COUNT(*) AS attempts, "
                   "AVG(100 * a.score / a.total) AS average FROM quiz_attempts a "
                   "JOIN quizzes z ON z.id = a.quiz_id JOIN topics t ON t.id = z.topic_id "
                   "JOIN subjects s ON s.id = t.subject_id WHERE a.total > 0 "
                   "GROUP BY t.id, t.name, s.name HAVING COUNT(*) >= 3 "
                   "ORDER BY average ASC, attempts DESC LIMIT 8")]
    gen = query_one("SELECT COUNT(*) AS total, COALESCE(SUM(success), 0) AS ok FROM ai_usage_logs "
                    "WHERE feature = 'quiz' AND created_at > %s", (utcnow() - timedelta(days=30),))
    ok = int(gen["ok"] or 0)
    return {
        "quizzes": totals["quizzes"], "linked": totals["linked"],
        "linked_percent": percent(totals["linked"], totals["quizzes"]),
        "attempts": totals["attempts"], "students": totals["students"], "average": pct(totals["average"]),
        "by_difficulty": by_difficulty, "by_subject": by_subject, "hardest": hardest,
        "chart": chart_logic.horizontal_bars([(r["name"], r["attempts"]) for r in by_subject]),
        "generation": {"total": gen["total"], "ok": ok, "rate": percent(ok, gen["total"])}}
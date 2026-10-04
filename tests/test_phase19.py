"""Run with:  python -m pytest -v   (MySQL is faked; the chart arithmetic needs no database at all.)"""
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app import create_app
from app import validators_curriculum as vc
from app.services import admin_service, analytics_service as an, chart_logic as cl
from app.services import curriculum_service as cs, user_service
from config import Config

ROOT = Path(__file__).resolve().parent.parent


class P19Config(Config):
    TESTING = True
    SECRET_KEY = "test-only-not-a-real-secret"
    WTF_CSRF_ENABLED = False


@pytest.fixture
def client():
    return create_app(P19Config).test_client()


USERS = {1: {"id": 1, "full_name": "Sample Student", "email": "s@example.com", "role": "student", "is_active": 1},
         2: {"id": 2, "full_name": "Sample Tutor", "email": "t@example.com", "role": "tutor", "is_active": 1},
         4: {"id": 4, "full_name": "An Admin", "email": "a@example.com", "role": "admin", "is_active": 1}}


def login_as(client, monkeypatch, user_id=4):
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: USERS[user_id])
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


# ======================= chart arithmetic =======================
TODAY = date(2026, 10, 6)


def test_days_are_philippine_days_and_the_window_is_respected():
    assert cl.day_list(TODAY, 3) == [date(2026, 10, 4), date(2026, 10, 5), date(2026, 10, 6)]
    times = [datetime(2026, 10, 5, 17, 0),      # 01:00 on Oct 6 in the Philippines
             datetime(2026, 10, 6, 1, 0),       # 09:00 on Oct 6
             datetime(2026, 10, 5, 15, 59),     # 23:59 on Oct 5
             datetime(2026, 10, 3, 17, 0),      # Oct 4, 01:00: the first day of the window
             datetime(2026, 10, 3, 15, 59),     # Oct 3, 23:59: just outside
             None]
    assert cl.bucket_by_day(times, TODAY, 3) == [1, 1, 2]
    assert cl.bucket_by_day([], TODAY, 3) == [0, 0, 0]


@pytest.mark.parametrize("peak,top", [(0, 4), (1, 1), (3, 5), (5, 5), (7, 10), (12, 20), (80, 100), (101, 200)])
def test_nice_top(peak, top):
    assert cl.nice_top(peak) == top


def test_the_line_chart_stays_inside_its_frame():
    days = cl.day_list(TODAY, 14)
    chart = cl.line_chart(days, [("A", "s1", list(range(14))), ("B", "s2", [0] * 14)])
    assert chart["width"] == 640 and len(chart["series"]) == 2 and chart["series"][0]["total"] == sum(range(14))
    for series in chart["series"]:
        for dot in series["dots"]:
            assert chart["left"] <= dot["x"] <= chart["right_x"] and 0 <= dot["y"] <= chart["height"]
    a = chart["series"][0]["dots"]
    assert a[0]["y"] > a[-1]["y"]                                    # bigger values are drawn higher
    assert chart["series"][0]["points"].count(",") == 14 and a[10]["day"] == "03 Oct"
    assert [t["label"] for t in chart["y_ticks"]] == [0, 10, 20]


def test_the_line_chart_labels_every_second_day_and_always_the_last():
    chart = cl.line_chart(cl.day_list(TODAY, 14), [("A", "s1", [1] * 14)])
    texts = [x["text"] for x in chart["x_labels"]]
    assert texts[-1] == "06 Oct" and len(texts) == 7
    short_chart = cl.line_chart(cl.day_list(TODAY, 5), [("A", "s1", [1] * 5)])
    assert len(short_chart["x_labels"]) == 5


def test_empty_and_single_day_charts_do_not_divide_by_zero():
    flat = cl.line_chart(cl.day_list(TODAY, 4), [("A", "s1", [0] * 4)])
    assert [t["label"] for t in flat["y_ticks"]] == [0, 2, 4]
    assert all(d["y"] == flat["series"][0]["dots"][0]["y"] for d in flat["series"][0]["dots"])
    one = cl.line_chart([TODAY], [("A", "s1", [3])])
    assert one["series"][0]["dots"][0]["x"] == one["left"]
    assert cl.line_chart([], [])["series"] == []


def test_bars_scale_to_the_largest_value():
    chart = cl.horizontal_bars([("Python", 10), ("Calculus", 5), ("Nothing", 0), ("Tiny", 1)], max_bar=200)
    widths = [r["bar_w"] for r in chart["rows"]]
    assert widths == [200, 100, 0, 20] and chart["rows"][1]["y"] == 30
    assert cl.horizontal_bars([("A", 1000), ("B", 1)], max_bar=200)["rows"][1]["bar_w"] == 2   # never invisible
    assert cl.horizontal_bars([])["rows"] == [] and cl.horizontal_bars([("A", 0)])["rows"][0]["bar_w"] == 0


def test_long_labels_are_shortened_but_kept_in_full():
    row = cl.horizontal_bars([("A very long subject name indeed", 3)])["rows"][0]
    assert len(row["label"]) <= 24 and row["label"].endswith("\u2026") and row["full"].startswith("A very long")


# ======================= analytics queries (faked) =======================
def test_activity_counts_each_series_per_philippine_day(monkeypatch):
    monkeypatch.setattr(an, "utcnow", lambda: datetime(2026, 10, 6, 2, 0))      # 10:00 on Oct 6 in the Philippines

    def fake_query_all(sql, params=None):
        assert params[1] == an.MAX_ROWS
        if "tutoring_requests" in sql:
            return [{"t": datetime(2026, 10, 5, 17, 0)}, {"t": datetime(2026, 10, 6, 1, 0)}, {"t": datetime(2026, 9, 1)}]
        if "quiz_attempts" in sql:
            return [{"t": datetime(2026, 10, 1, 4, 0)}]
        return []
    monkeypatch.setattr(an, "query_all", fake_query_all)
    result = an.activity(14)
    assert result["names"][0] == ("Tutoring requests", "s1") and result["days"] == 14
    by_name = {s["name"]: s for s in result["chart"]["series"]}
    assert by_name["Tutoring requests"]["total"] == 2 and by_name["Quiz attempts"]["total"] == 1
    assert by_name["Lessons completed"]["total"] == 0
    assert result["table"][-1] == {"day": "06 Oct", "values": [2, 0, 0, 0]} and len(result["table"]) == 14


def test_subject_charts(monkeypatch):
    def fake_query_all(sql, params=None):
        if "lesson_progress" in sql:
            return [{"name": "Python", "n": 9}]
        return [{"name": "Python", "n": 3}, {"name": "Algebra", "n": 1}]
    monkeypatch.setattr(an, "query_all", fake_query_all)
    result = an.subject_charts()
    assert result["requests_rows"] == [("Python", 3), ("Algebra", 1)] and result["lessons_rows"] == [("Python", 9)]
    assert result["requests"]["rows"][1]["bar_w"] < result["requests"]["rows"][0]["bar_w"]


def test_the_quiz_overview_rounds_orders_and_handles_empty_data(monkeypatch):
    monkeypatch.setattr(an, "utcnow", lambda: datetime(2026, 10, 6, 2, 0))

    def fake_query_one(sql, params=None):
        if "COUNT(DISTINCT user_id)" in sql:
            return {"quizzes": 8, "linked": 6, "attempts": 20, "students": 5, "average": Decimal("71.6667")}
        return {"total": 10, "ok": Decimal("9")}

    def fake_query_all(sql, params=None):
        if "GROUP BY z.difficulty" in sql:
            return [{"difficulty": "hard", "attempts": 2, "average": Decimal("40.0")},
                    {"difficulty": "easy", "attempts": 9, "average": 88.4}]
        if "HAVING COUNT(*) >= 3" in sql:
            return [{"topic": "Functions", "subject": "Python", "attempts": 4, "average": 52.5}]
        return [{"name": "Python", "attempts": 12, "average": 70}, {"name": "(subject removed)", "attempts": 1, "average": None}]
    monkeypatch.setattr(an, "query_one", fake_query_one)
    monkeypatch.setattr(an, "query_all", fake_query_all)
    d = an.quiz_overview()
    assert (d["quizzes"], d["attempts"], d["average"], d["linked_percent"]) == (8, 20, 72, 75)
    assert [r["difficulty"] for r in d["by_difficulty"]] == ["easy", "hard"] and d["by_difficulty"][0]["average"] == 88
    assert d["hardest"][0]["average"] == 52 and d["by_subject"][1]["average"] is None
    assert d["generation"] == {"total": 10, "ok": 9, "rate": 90} and len(d["chart"]["rows"]) == 2

    monkeypatch.setattr(an, "query_one", lambda sql, params=None: (
        {"quizzes": 0, "linked": 0, "attempts": 0, "students": 0, "average": None}
        if "COUNT(DISTINCT user_id)" in sql else {"total": 0, "ok": None}))
    monkeypatch.setattr(an, "query_all", lambda sql, params=None: [])
    empty = an.quiz_overview()
    assert empty["average"] is None and empty["linked_percent"] is None and empty["generation"]["rate"] is None


def test_analytics_never_selects_personal_data():
    source = (ROOT / "app" / "services" / "analytics_service.py").read_text(encoding="utf-8")
    for word in ("full_name", "email", "answer_text", "password", "ai_messages", "body"):
        assert word not in source


# ======================= validation =======================
def test_topic_validation():
    data, errors = vc.validate_topic({"name": "  Recursion  ", "level": "3", "position": " 4 "})
    assert errors == [] and data == {"name": "Recursion", "level": 3, "position": 4}
    assert vc.validate_topic({"name": "Loops", "level": "2", "position": ""})[0]["position"] is None
    for bad in ({"name": "x", "level": "1"}, {"name": "y" * 101, "level": "1"}, {"name": "Loops", "level": "0"},
                {"name": "Loops", "level": "5"}, {"name": "Loops", "level": "abc"}, {"name": "Loops"},
                {"name": "Loops", "level": "1", "position": "0"}, {"name": "Loops", "level": "1", "position": "100"},
                {"name": "Loops", "level": "1", "position": "x"}, {"name": "Loops", "level": "1", "position": "-2"}):
        assert vc.validate_topic(bad)[1]


GOOD_BODY = "A variable is a name for a value.\n\n    age = 17\n\nTry it yourself."


def test_lesson_validation_and_body_cleaning():
    data, errors = vc.validate_lesson({"title": " Variables ", "body": GOOD_BODY, "difficulty": "easy", "minutes": "5"})
    assert errors == [] and data["title"] == "Variables" and data["minutes"] == 5
    assert "    age = 17" in data["body"]                                   # indentation is kept
    dirty = "Line one\r\nLine\x00 two with a \u202e trick\rand a third line"
    assert vc.clean_body(dirty) == "Line one\nLine two with a  trick\nand a third line"
    assert vc.clean_body("\n\n  text here with indent\n\n") == "  text here with indent"
    assert vc.clean_body(None) == ""
    base = {"title": "Variables", "body": GOOD_BODY, "difficulty": "easy", "minutes": "5"}
    for bad in ({**base, "title": "ab"}, {**base, "title": "t" * 151}, {**base, "body": "too short"},
                {**base, "body": "b" * 8001}, {**base, "difficulty": "impossible"}, {**base, "minutes": "0"},
                {**base, "minutes": "121"}, {**base, "minutes": "x"}, {}):
        assert vc.validate_lesson(bad)[1]


def test_the_tree_groups_levels_topics_and_lessons():
    rows = [
        {"topic_id": 1, "topic_name": "Variables", "level": 1, "position": 1, "topic_active": 1,
         "lesson_id": 10, "title": "Intro", "difficulty": "easy", "minutes": 5, "lesson_active": 1},
        {"topic_id": 1, "topic_name": "Variables", "level": 1, "position": 1, "topic_active": 1,
         "lesson_id": 11, "title": "Naming", "difficulty": "easy", "minutes": 4, "lesson_active": 0},
        {"topic_id": 2, "topic_name": "Loops", "level": 2, "position": 1, "topic_active": 0,
         "lesson_id": None, "title": None, "difficulty": None, "minutes": None, "lesson_active": None}]
    levels = cs.build_tree(rows)
    assert [lv["level"] for lv in levels] == [1, 2]
    first = levels[0]["topics"][0]
    assert [l["id"] for l in first["lessons"]] == [10, 11] and first["lessons"][1]["active"] is False
    assert levels[1]["topics"][0]["lessons"] == [] and levels[1]["topics"][0]["active"] is False
    assert cs.build_tree([]) == []


# ======================= routes =======================
TOPIC = {"id": 7, "subject_id": 4, "name": "Loops", "level": 2, "position": 2, "is_active": 1,
         "subject_name": "Python Programming"}
LESSON = {"id": 9, "topic_id": 7, "title": "For loops", "body": "<script>alert(1)</script> for i in range(3):",
          "difficulty": "easy", "minutes": 6, "is_active": 1, "topic_name": "Loops", "subject_id": 4,
          "subject_name": "Python Programming"}


@pytest.fixture
def env(monkeypatch):
    e = {"created": [], "updated": [], "toggled": [], "audits": [], "exists": False, "fail": False,
         "topic": dict(TOPIC), "lesson": dict(LESSON), "tree": []}
    monkeypatch.setattr(cs, "list_subjects", lambda: [
        {"id": 4, "name": "<b>Python</b>", "category": None, "is_active": 1, "topics": 2, "lessons": 5}])
    monkeypatch.setattr(cs, "get_subject", lambda sid: {"id": 4, "name": "Python Programming", "category": None,
                                                        "is_active": 1} if sid == 4 else None)
    monkeypatch.setattr(cs, "subject_tree", lambda sid: e["tree"])
    monkeypatch.setattr(cs, "get_topic", lambda tid: e["topic"] if tid == 7 else None)
    monkeypatch.setattr(cs, "get_lesson", lambda lid: e["lesson"] if lid == 9 else None)

    def create_topic(sid, data):
        if e["exists"]:
            raise cs.TopicExists()
        e["created"].append(("topic", sid, data))
        return 31

    def create_lesson(tid, data):
        if e["exists"]:
            raise cs.LessonExists()
        e["created"].append(("lesson", tid, data))
        return 32

    def update_topic(tid, data):
        if e["exists"]:
            raise cs.TopicExists()
        if e["fail"]:
            raise RuntimeError("db down")
        e["updated"].append(("topic", tid, data))

    def update_lesson(lid, data):
        if e["exists"]:
            raise cs.LessonExists()
        e["updated"].append(("lesson", lid, data))

    monkeypatch.setattr(cs, "create_topic", create_topic)
    monkeypatch.setattr(cs, "create_lesson", create_lesson)
    monkeypatch.setattr(cs, "update_topic", update_topic)
    monkeypatch.setattr(cs, "update_lesson", update_lesson)
    monkeypatch.setattr(cs, "set_topic_active", lambda tid, active: e["toggled"].append(("topic", tid, active)))
    monkeypatch.setattr(cs, "set_lesson_active", lambda lid, active: e["toggled"].append(("lesson", lid, active)))
    monkeypatch.setattr(user_service, "log_audit", lambda *a, **k: e["audits"].append(a))
    return e


GETS = ["/admin/curriculum", "/admin/curriculum/4", "/admin/curriculum/4/topics/new",
        "/admin/curriculum/topics/7/edit", "/admin/curriculum/topics/7/lessons/new",
        "/admin/curriculum/lessons/9/edit", "/admin/quizzes"]
POSTS = ["/admin/curriculum/4/topics/new", "/admin/curriculum/topics/7/edit", "/admin/curriculum/topics/7/toggle",
         "/admin/curriculum/topics/7/lessons/new", "/admin/curriculum/lessons/9/edit",
         "/admin/curriculum/lessons/9/toggle"]


def test_only_administrators_reach_content_management(client, monkeypatch, env):
    for path in GETS:
        assert client.get(path).status_code == 302
    for path in POSTS:
        assert client.post(path, data={}).status_code == 302
    for user_id in (1, 2):
        login_as(client, monkeypatch, user_id)
        for path in GETS:
            assert client.get(path).status_code == 403
        for path in POSTS:
            assert client.post(path, data={"name": "Hack", "level": "1"}).status_code == 403
    assert env["created"] == [] and env["updated"] == [] and env["toggled"] == [] and env["audits"] == []


def test_unknown_ids_are_404(client, monkeypatch, env):
    login_as(client, monkeypatch)
    for path in ("/admin/curriculum/99", "/admin/curriculum/99/topics/new", "/admin/curriculum/topics/99/edit",
                 "/admin/curriculum/topics/99/lessons/new", "/admin/curriculum/lessons/99/edit"):
        assert client.get(path).status_code == 404
    for path in ("/admin/curriculum/topics/99/toggle", "/admin/curriculum/lessons/99/toggle"):
        assert client.post(path).status_code == 404
    assert env["toggled"] == []


def test_the_pages_load_escape_text_and_show_the_new_tabs(client, monkeypatch, env):
    login_as(client, monkeypatch)
    index = client.get("/admin/curriculum")
    assert index.status_code == 200 and b"&lt;b&gt;Python" in index.data and b"<b>Python</b>" not in index.data
    assert b"/admin/curriculum" in index.data and b"/admin/quizzes" in index.data           # the tab bar
    env["tree"] = cs.build_tree([{"topic_id": 7, "topic_name": "<i>Loops</i>", "level": 2, "position": 1,
                                  "topic_active": 0, "lesson_id": 9, "title": "For loops", "difficulty": "easy",
                                  "minutes": 6, "lesson_active": 0}])
    subject = client.get("/admin/curriculum/4")
    assert subject.status_code == 200 and b"&lt;i&gt;Loops" in subject.data and b"Hidden" in subject.data
    assert b"/admin/curriculum/topics/7/toggle" in subject.data and b"Show" in subject.data
    page = client.get("/admin/curriculum/lessons/9/edit")
    assert b"<script>alert(1)</script>" not in page.data and b"&lt;script&gt;alert(1)" in page.data
    assert b"Saved text, as students see it" in page.data


def test_a_database_error_shows_a_message_not_a_crash(client, monkeypatch, env):
    login_as(client, monkeypatch)

    def broken(*a):
        raise RuntimeError("db down")
    monkeypatch.setattr(cs, "list_subjects", broken)
    monkeypatch.setattr(cs, "subject_tree", broken)
    assert b"Could not load the subjects" in client.get("/admin/curriculum").data
    assert b"Could not load the topics" in client.get("/admin/curriculum/4").data


def test_creating_a_topic_saves_cleans_and_audits(client, monkeypatch, env):
    login_as(client, monkeypatch)
    response = client.post("/admin/curriculum/4/topics/new", data={"name": "  Recursion  ", "level": "3", "position": ""})
    assert response.status_code == 302 and response.headers["Location"].endswith("/admin/curriculum/4")
    assert env["created"] == [("topic", 4, {"name": "Recursion", "level": 3, "position": None})]
    audit = env["audits"][0]
    assert audit[0] == 4 and audit[1] == "topic_created" and audit[2] == "topic" and audit[3] == 31


@pytest.mark.parametrize("form", [{"name": "x", "level": "1"}, {"name": "Loops", "level": "9"},
                                  {"name": "Loops", "level": "1", "position": "500"}, {}])
def test_bad_topics_are_not_saved(client, monkeypatch, env, form):
    login_as(client, monkeypatch)
    page = client.post("/admin/curriculum/4/topics/new", data=form)
    assert page.status_code == 200 and env["created"] == [] and env["audits"] == []


def test_a_duplicate_topic_or_lesson_gets_a_clear_message(client, monkeypatch, env):
    login_as(client, monkeypatch)
    env["exists"] = True
    page = client.post("/admin/curriculum/4/topics/new", data={"name": "Loops", "level": "2"})
    assert b"already has a topic" in page.data and env["audits"] == []
    page = client.post("/admin/curriculum/topics/7/lessons/new",
                       data={"title": "For loops", "body": GOOD_BODY, "difficulty": "easy", "minutes": "5"})
    assert b"already has a lesson" in page.data and env["audits"] == []


def test_editing_a_topic_keeps_the_position_when_left_blank(client, monkeypatch, env):
    login_as(client, monkeypatch)
    assert client.post("/admin/curriculum/topics/7/edit", data={"name": "While loops", "level": "3", "position": ""}).status_code == 302
    assert env["updated"] == [("topic", 7, {"name": "While loops", "level": 3, "position": 2})]
    assert env["audits"][0][1] == "topic_updated"
    env["fail"] = True
    page = client.post("/admin/curriculum/topics/7/edit", data={"name": "Again", "level": "3"})
    assert b"Could not save the topic" in page.data and len(env["audits"]) == 1


def test_creating_and_editing_lessons(client, monkeypatch, env):
    login_as(client, monkeypatch)
    form = {"title": " While loops ", "body": GOOD_BODY, "difficulty": "medium", "minutes": "8"}
    response = client.post("/admin/curriculum/topics/7/lessons/new", data=form)
    assert response.status_code == 302 and response.headers["Location"].endswith("/admin/curriculum/4")
    kind, topic_id, data = env["created"][0]
    assert (kind, topic_id, data["title"], data["difficulty"], data["minutes"]) == ("lesson", 7, "While loops", "medium", 8)
    assert env["audits"][0][1] == "lesson_created" and env["audits"][0][3] == 32
    assert client.post("/admin/curriculum/lessons/9/edit", data=form).status_code == 302
    assert env["updated"][0][0:2] == ("lesson", 9) and env["audits"][1][1] == "lesson_updated"
    bad = client.post("/admin/curriculum/topics/7/lessons/new", data={**form, "body": "short"})
    assert bad.status_code == 200 and len(env["created"]) == 1


def test_hiding_and_showing_never_deletes_and_is_audited(client, monkeypatch, env):
    login_as(client, monkeypatch)
    assert client.post("/admin/curriculum/topics/7/toggle").status_code == 302
    assert env["toggled"] == [("topic", 7, False)] and env["audits"][0][1] == "topic_hidden"
    env["topic"]["is_active"] = 0
    client.post("/admin/curriculum/topics/7/toggle")
    assert env["toggled"][-1] == ("topic", 7, True) and env["audits"][1][1] == "topic_shown"
    client.post("/admin/curriculum/lessons/9/toggle")
    assert env["toggled"][-1] == ("lesson", 9, False) and env["audits"][2][1] == "lesson_hidden"
    source = (ROOT / "app" / "services" / "curriculum_service.py").read_text(encoding="utf-8")
    assert "DELETE" not in source.upper()


def test_a_failed_audit_never_undoes_a_change(client, monkeypatch, env):
    login_as(client, monkeypatch)

    def broken(*a, **k):
        raise RuntimeError("audit table missing")
    monkeypatch.setattr(user_service, "log_audit", broken)
    response = client.post("/admin/curriculum/4/topics/new", data={"name": "Recursion", "level": "3"})
    assert response.status_code == 302 and len(env["created"]) == 1


def test_a_failed_toggle_reports_an_error(client, monkeypatch, env):
    login_as(client, monkeypatch)

    def broken(tid, active):
        raise RuntimeError("db down")
    monkeypatch.setattr(cs, "set_topic_active", broken)
    page = client.post("/admin/curriculum/topics/7/toggle", follow_redirects=True)
    assert b"Nothing was changed" in page.data and env["audits"] == []


# ======================= dashboard and quiz overview =======================
def sample_activity():
    days = cl.day_list(TODAY, 14)
    series = [("Tutoring requests", "s1", [0] * 13 + [2]), ("Quiz attempts", "s2", [1] * 14),
              ("Lessons completed", "s3", [0] * 14), ("AI requests", "s4", [3] * 14)]
    return {"days": 14, "chart": cl.line_chart(days, series), "names": [(n, c) for n, c, _ in series],
            "table": [{"day": d.strftime("%d %b"), "values": [s[2][i] for s in series]} for i, d in enumerate(days)]}


def test_the_dashboard_draws_safe_accessible_charts(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(admin_service, "overview", lambda: {
        "users": {"student": 7, "tutor": 3, "admin": 1}, "approved_tutors": 2, "pending_tutors": 1,
        "active_subjects": 8, "requests_total": 12, "requests_open": 4, "sessions_completed": 5,
        "feedback_visible": 3, "inactive_users": 1})
    monkeypatch.setattr(an, "activity", sample_activity)
    monkeypatch.setattr(an, "subject_charts", lambda: {
        "requests": cl.horizontal_bars([("<b>Python</b>", 5)]), "requests_rows": [("<b>Python</b>", 5)],
        "lessons": cl.horizontal_bars([]), "lessons_rows": []})
    page = client.get("/admin/dashboard")
    assert page.status_code == 200 and page.data.count(b"<svg") == 2 and page.data.count(b'role="img"') == 2
    assert b"polyline" in page.data and b"View as a table" in page.data and b"No lessons completed yet" in page.data
    assert b"<b>Python</b>" not in page.data and b"&lt;b&gt;Python" in page.data
    assert b"style=" not in page.data and b"Completed sessions" in page.data


def test_charts_failing_does_not_hide_the_numbers(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(admin_service, "overview", lambda: {
        "users": {"student": 7, "tutor": 3, "admin": 1}, "approved_tutors": 2, "pending_tutors": 1,
        "active_subjects": 8, "requests_total": 12, "requests_open": 4, "sessions_completed": 5,
        "feedback_visible": 3, "inactive_users": 1})

    def broken(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(an, "activity", broken)
    page = client.get("/admin/dashboard")
    assert page.status_code == 200 and b"Completed sessions" in page.data and b"charts could not be loaded" in page.data


def test_the_quiz_overview_page(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(an, "quiz_overview", lambda: {
        "quizzes": 8, "linked": 6, "linked_percent": 75, "attempts": 20, "students": 5, "average": 72,
        "by_difficulty": [{"difficulty": "easy", "attempts": 9, "average": 88}],
        "by_subject": [{"name": "Python", "attempts": 12, "average": 70}],
        "hardest": [{"topic": "<i>Functions</i>", "subject": "Python", "attempts": 4, "average": 52}],
        "chart": cl.horizontal_bars([("Python", 12)]),
        "generation": {"total": 10, "ok": 9, "rate": 90}})
    page = client.get("/admin/quizzes")
    assert page.status_code == 200 and b"72%" in page.data and b"90%" in page.data and b"<svg" in page.data
    assert b"<i>Functions</i>" not in page.data and b"&lt;i&gt;Functions" in page.data
    assert b"No student names" in page.data


def test_the_quiz_overview_survives_a_database_error(client, monkeypatch):
    login_as(client, monkeypatch)

    def broken():
        raise RuntimeError("db down")
    monkeypatch.setattr(an, "quiz_overview", broken)
    assert b"Could not load the quiz overview" in client.get("/admin/quizzes").data


# ======================= students never see hidden content =======================
def test_students_are_only_ever_shown_visible_topics_and_lessons():
    source = (ROOT / "app" / "services" / "learning_service.py").read_text(encoding="utf-8")
    assert source.count("l.is_active = 1") >= 3 and source.count("t.is_active = 1") >= 3
    agent = (ROOT / "app" / "services" / "recommendation_service.py").read_text(encoding="utf-8")
    assert "l.is_active = 1" in agent and "t.is_active = 1" in agent


# ======================= hygiene =======================
def test_chart_logic_is_pure():
    source = (ROOT / "app" / "services" / "chart_logic.py").read_text(encoding="utf-8")
    for word in ("flask", "app.db", "query_", "requests"):
        assert word not in source


def test_the_charts_partial_has_no_inline_scripts_or_styles():
    text = (ROOT / "app" / "templates" / "partials" / "charts.html").read_text(encoding="utf-8")
    assert "<script" not in text and "style=" not in text and "onclick" not in text.lower()
    assert text.count('role="img"') == 2 and "<title>" in text
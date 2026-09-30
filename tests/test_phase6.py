"""Run with:  python -m pytest -v
Ollama and MySQL are FAKED. These tests prove our validation, grading, hiding of
answers and permissions. Only the manual checklist proves a real model makes good quizzes."""
import json
import random
from datetime import datetime
import pytest
from werkzeug.datastructures import MultiDict
from config import Config
from app import create_app
from app import validators_quiz as vq
from app.ai import ollama_client as oc
from app.ai import quiz_logic as ql
from app.services import ai_service, quiz_generator, quiz_service as qs
from app.services import subject_service, user_service

ALL_TYPES = ("mcq", "tf", "short")


class P6Config(Config):
    TESTING = True
    SECRET_KEY = "test-only-not-a-real-secret"
    WTF_CSRF_ENABLED = False
    OLLAMA_MODEL = "test-model"


@pytest.fixture
def app():
    return create_app(P6Config)


@pytest.fixture
def client(app):
    return app.test_client()


def login_as(client, monkeypatch, role="student"):
    fake = {"id": 1, "full_name": "Test Person", "email": "test@example.com",
            "role": role, "is_active": 1}
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: fake)
    with client.session_transaction() as sess:
        sess["user_id"] = 1


def good_payload():
    return {"questions": [
        {"type": "mcq", "question": "What is 2 + 2?", "options": ["3", "4", "5", "6"],
         "answer_index": 1, "explanation": "Two plus two equals four."},
        {"type": "tf", "question": "The derivative of a constant is zero.", "answer": True,
         "explanation": "A constant does not change."},
        {"type": "short", "question": "What is the derivative of x squared?", "answer": "2x",
         "accepted_answers": ["2 x"], "explanation": "Use the power rule."},
    ]}


# ---------- reading the AI's JSON ----------
def test_extract_json_handles_fences_thinking_and_extra_text():
    payload = json.dumps({"a": 1})
    assert ql.extract_json(payload) == {"a": 1}
    assert ql.extract_json("```json\n" + payload + "\n```") == {"a": 1}
    assert ql.extract_json("<think>hmm</think>" + payload) == {"a": 1}
    assert ql.extract_json("Sure! Here you go: " + payload + " Enjoy.") == {"a": 1}


@pytest.mark.parametrize("bad", ["", "no json here", "{broken", None, 42])
def test_extract_json_rejects_garbage(bad):
    with pytest.raises(ql.QuizFormatError):
        ql.extract_json(bad)


# ---------- validating questions ----------
def test_good_quiz_is_accepted():
    questions = ql.parse_quiz(json.dumps(good_payload()), 3, ALL_TYPES, rng=random.Random(1))
    assert [q["type"] for q in questions] == ["mcq", "tf", "short"]


def test_mcq_shuffle_keeps_the_right_answer_right():
    for seed in range(20):
        q = ql.parse_quiz(json.dumps(good_payload()), 3, ALL_TYPES, rng=random.Random(seed))[0]
        assert q["options"][int(q["correct"])] == "4"
        assert sorted(q["options"]) == ["3", "4", "5", "6"]


def test_true_false_accepts_string_answers():
    payload = {"questions": [{"type": "tf", "question": "Water boils at 100 C at sea level.",
                              "answer": "True", "explanation": "Standard pressure."}]}
    q = ql.parse_quiz(json.dumps(payload), 1, ALL_TYPES)[0]
    assert q["correct"] == "true"


@pytest.mark.parametrize("bad", [
    {"type": "mcq", "question": "Pick one please", "options": ["a", "b", "c"], "answer_index": 0, "explanation": "x1x"},
    {"type": "mcq", "question": "Pick one please", "options": ["a", "A", "c", "d"], "answer_index": 0, "explanation": "x1x"},
    {"type": "mcq", "question": "Pick one please", "options": ["a", "b", "c", "d"], "answer_index": 4, "explanation": "x1x"},
    {"type": "mcq", "question": "Pick one please", "options": ["a", "b", "c", "d"], "answer_index": True, "explanation": "x1x"},
    {"type": "mcq", "question": "Pick one please", "options": ["a", "b", "c", "d"], "answer_index": 0},
    {"type": "tf", "question": "Is this valid input?", "answer": "maybe", "explanation": "x1x"},
    {"type": "short", "question": "Say something short", "answer": "", "explanation": "x1x"},
    {"type": "essay", "question": "Discuss at length", "answer": "x", "explanation": "x1x"},
    "not a dict", None,
])
def test_invalid_questions_are_rejected(bad):
    assert ql.clean_question(bad, ALL_TYPES, random.Random(0)) is None


def test_types_the_student_did_not_ask_for_are_dropped():
    # One mcq question exists in the payload, and we only ask for one question.
    questions = ql.parse_quiz(json.dumps(good_payload()), 1, ("mcq",))
    assert [q["type"] for q in questions] == ["mcq"]


def test_quiz_is_rejected_when_the_wanted_type_is_mostly_missing():
    # Asking for 3 multiple-choice questions when the AI made only 1 is not acceptable.
    with pytest.raises(ql.QuizFormatError):
        ql.parse_quiz(json.dumps(good_payload()), 3, ("mcq",))


def test_bad_questions_dropped_but_enough_good_ones_pass():
    payload = good_payload()
    payload["questions"].append({"type": "tf", "question": "Broken one here", "answer": "maybe",
                                 "explanation": "x1x"})
    assert len(ql.parse_quiz(json.dumps(payload), 5, ALL_TYPES)) == 3   # 3 >= half of 5


def test_too_few_usable_questions_is_an_error():
    with pytest.raises(ql.QuizFormatError):
        ql.parse_quiz(json.dumps(good_payload()), 10, ALL_TYPES)        # 3 < half of 10


def test_duplicates_are_removed_and_extra_questions_trimmed():
    payload = good_payload()
    payload["questions"].append(dict(payload["questions"][0]))
    assert len(ql.parse_quiz(json.dumps(payload), 3, ALL_TYPES)) == 3
    assert len(ql.parse_quiz(json.dumps(payload), 2, ALL_TYPES)) == 2


@pytest.mark.parametrize("payload", [{}, {"questions": []}, {"questions": "x"}, [], "x"])
def test_wrong_shapes_are_errors(payload):
    with pytest.raises(ql.QuizFormatError):
        ql.parse_quiz(json.dumps(payload), 3, ALL_TYPES)


# ---------- grading ----------
def test_grading_mcq_and_tf():
    assert ql.grade_answer("mcq", "2", None, "2") is True
    assert ql.grade_answer("mcq", "2", None, "3") is False
    assert ql.grade_answer("mcq", "2", None, "") is False
    assert ql.grade_answer("tf", "true", None, "TRUE") is True
    assert ql.grade_answer("tf", "true", None, "false") is False
    assert ql.grade_answer("tf", "true", None, None) is False


def test_grading_short_answers_is_forgiving_but_not_careless():
    assert ql.grade_answer("short", "mitochondria", None, "The Mitochondria.") is True
    assert ql.grade_answer("short", "2x", ["2 x"], "2 x") is True
    assert ql.grade_answer("short", "3.5", None, "3.5") is True
    assert ql.grade_answer("short", "3.5", None, "35") is False
    assert ql.grade_answer("short", "mitochondria", None, "nucleus") is False
    assert ql.grade_answer("short", "mitochondria", None, "   ") is False


# ---------- answers stay hidden until revealed ----------
ROW = {"position": 1, "q_type": "mcq", "question_text": "Pick the answer",
       "options": json.dumps(["a", "b", "c", "d"]), "correct_answer": "2",
       "explanation": "Because c is right.", "answer_text": "0", "is_correct": 0}


def test_review_hides_answer_and_explanation_until_revealed():
    hidden = qs.build_review_items([ROW], revealed=False)[0]
    assert hidden["correct_answer_text"] is None and hidden["explanation"] is None
    assert hidden["your_answer"] == "a" and hidden["is_correct"] is False
    shown = qs.build_review_items([ROW], revealed=True)[0]
    assert shown["correct_answer_text"] == "c" and shown["explanation"] == "Because c is right."


def test_answer_label_is_safe_with_bad_values():
    assert qs.answer_label("mcq", ["a", "b"], "-1") == "No answer"
    assert qs.answer_label("mcq", ["a", "b"], "9") == "No answer"
    assert qs.answer_label("mcq", None, "0") == "No answer"
    assert qs.answer_label("tf", None, "banana") == "No answer"
    assert qs.answer_label("short", None, None) == "No answer"


def test_the_quiz_page_query_never_selects_answers():
    sql = qs.TAKE_SQL.lower()
    assert "correct_answer" not in sql and "explanation" not in sql and "accepted" not in sql


# ---------- form validation ----------
def form(**overrides):
    base = {"subject_id": "1", "topic": "Limits", "difficulty": "easy", "count": "5",
            "types": ["mcq", "tf"], "mode": "practice"}
    base.update(overrides)
    return MultiDict(base)


def test_valid_generate_form():
    data, errors = vq.validate_generate_form(form(), {1, 2})
    assert errors == [] and data["types"] == ["mcq", "tf"] and data["count"] == 5


@pytest.mark.parametrize("bad", [
    {"subject_id": "99"}, {"subject_id": "abc"}, {"topic": "x"}, {"topic": "y" * 101},
    {"difficulty": "impossible"}, {"count": "2"}, {"count": "11"}, {"count": "many"},
    {"types": ["essay"]}, {"types": []}, {"mode": "cheat"},
])
def test_bad_generate_forms_are_rejected(bad):
    _, errors = vq.validate_generate_form(form(**bad), {1, 2})
    assert errors


# ---------- the generator (fake Ollama, fake database) ----------
DATA = {"subject_id": 1, "topic": "Limits", "difficulty": "easy", "count": 3,
        "types": list(ALL_TYPES), "mode": "practice"}


@pytest.fixture
def gen_env(monkeypatch):
    logs = []
    monkeypatch.setattr(ai_service, "_rate_limited", lambda uid: False)
    monkeypatch.setattr(ai_service, "_log_usage", lambda *a, **k: logs.append(a))
    return logs


def test_generator_success_saves_validated_questions(app, monkeypatch, gen_env):
    monkeypatch.setattr(oc, "chat", lambda messages, **k: json.dumps(good_payload()))
    saved = {}

    def fake_create(user_id, subject_id, topic, difficulty, mode, questions):
        saved["questions"] = questions
        return 9
    monkeypatch.setattr(qs, "create_quiz", fake_create)
    with app.app_context():
        status, body = quiz_generator.generate_quiz(1, 1, "Calculus 1", DATA)
    assert status == 200 and body == {"ok": True, "quiz_id": 9, "count": 3}
    assert len(saved["questions"]) == 3 and gen_env[-1][3] is True


def test_generator_bad_output_saves_nothing(app, monkeypatch, gen_env):
    monkeypatch.setattr(oc, "chat", lambda messages, **k: "Sorry, I cannot do that.")
    monkeypatch.setattr(qs, "create_quiz", lambda *a, **k: pytest.fail("must not save"))
    with app.app_context():
        status, body = quiz_generator.generate_quiz(1, 1, "Calculus 1", DATA)
    assert status == 502 and body["error"] == quiz_generator.BAD_FORMAT
    assert gen_env[-1][3] is False and gen_env[-1][4] == "bad_format"


@pytest.mark.parametrize("error,status", [
    (oc.OllamaUnavailable(), 503), (oc.OllamaModelMissing(), 503), (oc.OllamaTimeout(), 504),
])
def test_generator_maps_ollama_errors(app, monkeypatch, gen_env, error, status):
    def failing(messages, **k):
        raise error
    monkeypatch.setattr(oc, "chat", failing)
    with app.app_context():
        got_status, body = quiz_generator.generate_quiz(1, 1, "Calculus 1", DATA)
    assert got_status == status and body["error"] == ai_service.ERROR_MESSAGES[error.code]


def test_generator_respects_rate_limit(app, monkeypatch, gen_env):
    monkeypatch.setattr(ai_service, "_rate_limited", lambda uid: True)
    monkeypatch.setattr(oc, "chat", lambda *a, **k: pytest.fail("model must not be called"))
    with app.app_context():
        assert quiz_generator.generate_quiz(1, 1, "Calculus 1", DATA)[0] == 429


# ---------- routes and permissions ----------
SUBJECTS = [{"id": 1, "name": "Calculus 1", "category": "Math", "is_active": 1}]


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setattr(subject_service, "list_subjects", lambda active_only=True: SUBJECTS)
    monkeypatch.setattr(qs, "list_quizzes", lambda uid: [])


@pytest.mark.parametrize("path", ["/student/quizzes/", "/student/quizzes/1/take",
                                  "/student/quizzes/attempts/1", "/student/quizzes/1/history"])
def test_anonymous_users_are_sent_to_login(client, path):
    response = client.get(path)
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_only_students_can_use_quizzes(client, monkeypatch, ready):
    for role in ("tutor", "admin"):
        login_as(client, monkeypatch, role)
        assert client.get("/student/quizzes/").status_code == 403
        assert client.post("/student/quizzes/generate", data=form().to_dict()).status_code == 403
        assert client.post("/student/quizzes/1/submit").status_code == 403
        assert client.post("/student/quizzes/attempts/1/reveal").status_code == 403


def test_index_page_loads(client, monkeypatch, ready):
    login_as(client, monkeypatch)
    response = client.get("/student/quizzes/")
    assert response.status_code == 200 and b"Calculus 1" in response.data


def test_bad_generate_input_returns_400_and_never_calls_the_ai(client, monkeypatch, ready):
    login_as(client, monkeypatch)
    monkeypatch.setattr(quiz_generator, "generate_quiz",
                        lambda *a, **k: pytest.fail("AI must not be called"))
    response = client.post("/student/quizzes/generate",
                           data={"subject_id": "99", "topic": "x", "count": "50"})
    assert response.status_code == 400


def test_generate_success_redirects_to_the_quiz(client, monkeypatch, ready):
    login_as(client, monkeypatch)
    monkeypatch.setattr(quiz_generator, "generate_quiz",
                        lambda *a, **k: (200, {"ok": True, "quiz_id": 7, "count": 5}))
    response = client.post("/student/quizzes/generate",
                           data={"subject_id": "1", "topic": "Limits", "difficulty": "easy",
                                 "count": "5", "types": ["mcq", "tf"], "mode": "practice"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/student/quizzes/7/take")


def test_generate_failure_shows_a_clear_message(client, monkeypatch, ready):
    login_as(client, monkeypatch)
    monkeypatch.setattr(quiz_generator, "generate_quiz",
                        lambda *a, **k: (502, {"ok": False, "error": quiz_generator.BAD_FORMAT}))
    response = client.post("/student/quizzes/generate",
                           data={"subject_id": "1", "topic": "Limits", "difficulty": "easy",
                                 "count": "5", "types": ["mcq"], "mode": "practice"})
    assert response.status_code == 502 and b"did not produce a usable quiz" in response.data


def test_someone_elses_quiz_is_404(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(qs, "get_quiz", lambda qid, uid: None)
    monkeypatch.setattr(qs, "get_attempt_review", lambda aid, uid: (None, []))
    assert client.get("/student/quizzes/5/take").status_code == 404
    assert client.post("/student/quizzes/5/submit").status_code == 404
    assert client.get("/student/quizzes/5/history").status_code == 404
    assert client.get("/student/quizzes/attempts/5").status_code == 404


def test_take_page_shows_questions_and_no_answers(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(qs, "get_quiz", lambda qid, uid: {
        "id": 1, "topic": "Limits", "difficulty": "easy", "mode": "test",
        "question_count": 2, "subject_name": "Calculus 1"})
    monkeypatch.setattr(qs, "get_questions_for_taking", lambda qid: [
        {"id": 10, "position": 1, "q_type": "mcq", "question_text": "What is 2 + 2?",
         "options": ["3", "4", "5", "6"]},
        {"id": 11, "position": 2, "q_type": "short", "question_text": "Name the rule.",
         "options": None}])
    response = client.get("/student/quizzes/1/take")
    assert response.status_code == 200
    assert b"What is 2 + 2?" in response.data and b'name="q_10"' in response.data
    assert b"Explanation" not in response.data


def test_submit_grades_then_redirects_to_the_result(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(qs, "get_quiz", lambda qid, uid: {"id": 1, "mode": "practice"})
    monkeypatch.setattr(qs, "save_attempt", lambda quiz, uid, form: 33)
    response = client.post("/student/quizzes/1/submit", data={"q_10": "1"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/student/quizzes/attempts/33")


ATTEMPT = {"id": 33, "quiz_id": 1, "score": 1, "total": 2, "answers_revealed": 0,
           "submitted_at": datetime(2026, 10, 6, 6, 0), "topic": "Limits",
           "difficulty": "easy", "mode": "test", "subject_name": "Calculus 1"}


def test_test_mode_result_hides_explanations_and_offers_reveal(client, monkeypatch):
    login_as(client, monkeypatch)
    items = qs.build_review_items([ROW], revealed=False)
    monkeypatch.setattr(qs, "get_attempt_review", lambda aid, uid: (dict(ATTEMPT), items))
    response = client.get("/student/quizzes/attempts/33")
    assert response.status_code == 200
    assert b"Reveal answers" in response.data and b"Because c is right." not in response.data
    assert b"not proof" in response.data


def test_revealed_result_shows_answers_and_explanations(client, monkeypatch):
    login_as(client, monkeypatch)
    items = qs.build_review_items([ROW], revealed=True)
    attempt = dict(ATTEMPT, answers_revealed=1)
    monkeypatch.setattr(qs, "get_attempt_review", lambda aid, uid: (attempt, items))
    response = client.get("/student/quizzes/attempts/33")
    assert b"Because c is right." in response.data and b"Reveal answers" not in response.data


def test_reveal_updates_and_redirects(client, monkeypatch):
    login_as(client, monkeypatch)
    called = {}
    monkeypatch.setattr(qs, "reveal_attempt", lambda aid, uid: called.update(a=aid, u=uid))
    response = client.post("/student/quizzes/attempts/33/reveal")
    assert response.status_code == 302 and called == {"a": 33, "u": 1}


def test_ai_html_is_escaped_in_the_result_page(client, monkeypatch):
    login_as(client, monkeypatch)
    row = dict(ROW, question_text="<script>alert(1)</script>")
    items = qs.build_review_items([row], revealed=False)
    monkeypatch.setattr(qs, "get_attempt_review", lambda aid, uid: (dict(ATTEMPT), items))
    response = client.get("/student/quizzes/attempts/33")
    assert b"<script>alert(1)</script>" not in response.data
    assert b"&lt;script&gt;" in response.data
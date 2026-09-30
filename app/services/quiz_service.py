"""Database work for quizzes, attempts and reviews."""
import json
from app.ai import quiz_logic
from app.db import execute, get_connection, query_all, query_one
from app.timeutil import utcnow

# NOTE: these two queries deliberately choose different columns.
# The quiz page must NEVER receive the answer or the explanation.
TAKE_SQL = ("SELECT id, position, q_type, question_text, options FROM quiz_questions "
            "WHERE quiz_id = %s ORDER BY position")
GRADE_SQL = ("SELECT id, q_type, correct_answer, accepted_answers FROM quiz_questions "
             "WHERE quiz_id = %s ORDER BY position")


def load_json(value):
    """MySQL JSON columns come back from PyMySQL as text."""
    if value is None or isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def answer_label(q_type, options, value):
    """Turn a stored answer into readable text."""
    if value is None or value == "":
        return "No answer"
    if q_type == "mcq":
        try:
            index = int(value)
            if 0 <= index < len(options):
                return options[index]
        except (TypeError, ValueError):
            pass
        return "No answer"
    if q_type == "tf":
        text = str(value).lower()
        return {"true": "True", "false": "False"}.get(text, "No answer")
    return str(value)


def build_review_items(rows, revealed):
    """Turns database rows into what the result page shows. If answers are NOT
    revealed, the correct answer and explanation are left out here, so a template
    can never leak them."""
    items = []
    for row in rows:
        options = load_json(row["options"]) or []
        item = {
            "position": row["position"],
            "q_type": row["q_type"],
            "question_text": row["question_text"],
            "is_correct": bool(row["is_correct"]),
            "your_answer": answer_label(row["q_type"], options, row["answer_text"]),
            "correct_answer_text": None,
            "explanation": None,
        }
        if revealed:
            item["correct_answer_text"] = answer_label(row["q_type"], options, row["correct_answer"])
            item["explanation"] = row["explanation"]
        items.append(item)
    return items


# ---------- creating ----------
def create_quiz(user_id, subject_id, topic, difficulty, mode, questions):
    """Save a quiz and all its (already validated) questions in ONE transaction."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO quizzes (user_id, subject_id, topic, difficulty, mode, "
                "question_count, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (user_id, subject_id, topic, difficulty, mode, len(questions), utcnow()),
            )
            quiz_id = cur.lastrowid
            for position, q in enumerate(questions, start=1):
                cur.execute(
                    "INSERT INTO quiz_questions (quiz_id, position, q_type, question_text, "
                    "options, correct_answer, accepted_answers, explanation) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (quiz_id, position, q["type"], q["question"],
                     json.dumps(q["options"], ensure_ascii=False) if q["options"] else None,
                     q["correct"],
                     json.dumps(q["accepted"], ensure_ascii=False) if q["accepted"] else None,
                     q["explanation"]),
                )
        conn.commit()
        return quiz_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------- reading ----------
def list_quizzes(user_id):
    return query_all(
        "SELECT z.id, z.topic, z.difficulty, z.mode, z.question_count, z.created_at, "
        "s.name AS subject_name, "
        "(SELECT COUNT(*) FROM quiz_attempts a WHERE a.quiz_id = z.id) AS attempts, "
        "(SELECT a.id FROM quiz_attempts a WHERE a.quiz_id = z.id "
        "   ORDER BY a.submitted_at DESC, a.id DESC LIMIT 1) AS last_attempt_id, "
        "(SELECT a.score FROM quiz_attempts a WHERE a.quiz_id = z.id "
        "   ORDER BY a.submitted_at DESC, a.id DESC LIMIT 1) AS last_score "
        "FROM quizzes z LEFT JOIN subjects s ON s.id = z.subject_id "
        "WHERE z.user_id = %s ORDER BY z.created_at DESC, z.id DESC LIMIT 30",
        (user_id,),
    )


def get_quiz(quiz_id, user_id):
    """Only the quiz's owner can load it."""
    return query_one(
        "SELECT z.id, z.topic, z.difficulty, z.mode, z.question_count, z.created_at, "
        "s.name AS subject_name FROM quizzes z LEFT JOIN subjects s ON s.id = z.subject_id "
        "WHERE z.id = %s AND z.user_id = %s",
        (quiz_id, user_id),
    )


def get_questions_for_taking(quiz_id):
    rows = query_all(TAKE_SQL, (quiz_id,))
    for row in rows:
        row["options"] = load_json(row["options"])
    return rows


def list_attempts(quiz_id, user_id):
    return query_all(
        "SELECT id, score, total, answers_revealed, submitted_at FROM quiz_attempts "
        "WHERE quiz_id = %s AND user_id = %s ORDER BY submitted_at DESC, id DESC",
        (quiz_id, user_id),
    )


def recent_attempts(user_id, limit=3):
    return query_all(
        "SELECT a.id, a.score, a.total, a.submitted_at, z.topic, s.name AS subject_name "
        "FROM quiz_attempts a JOIN quizzes z ON z.id = a.quiz_id "
        "LEFT JOIN subjects s ON s.id = z.subject_id WHERE a.user_id = %s "
        "ORDER BY a.submitted_at DESC, a.id DESC LIMIT %s",
        (user_id, limit),
    )


def get_attempt_review(attempt_id, user_id):
    """Returns (attempt, items), or (None, []) if it is not this user's attempt."""
    attempt = query_one(
        "SELECT a.id, a.quiz_id, a.score, a.total, a.answers_revealed, a.submitted_at, "
        "z.topic, z.difficulty, z.mode, s.name AS subject_name "
        "FROM quiz_attempts a JOIN quizzes z ON z.id = a.quiz_id "
        "LEFT JOIN subjects s ON s.id = z.subject_id "
        "WHERE a.id = %s AND a.user_id = %s",
        (attempt_id, user_id),
    )
    if attempt is None:
        return None, []
    rows = query_all(
        "SELECT q.position, q.q_type, q.question_text, q.options, q.correct_answer, "
        "q.explanation, ans.answer_text, ans.is_correct "
        "FROM quiz_answers ans JOIN quiz_questions q ON q.id = ans.question_id "
        "WHERE ans.attempt_id = %s ORDER BY q.position",
        (attempt_id,),
    )
    return attempt, build_review_items(rows, bool(attempt["answers_revealed"]))


# ---------- writing ----------
def save_attempt(quiz, user_id, form):
    """Grade the submitted form ON THE SERVER and store the attempt. Returns its id."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(GRADE_SQL, (quiz["id"],))
            questions = cur.fetchall()

            results, score = [], 0
            for q in questions:
                text = (form.get(f"q_{q['id']}") or "").strip()[:500]
                correct = quiz_logic.grade_answer(
                    q["q_type"], q["correct_answer"], load_json(q["accepted_answers"]), text)
                score += 1 if correct else 0
                results.append((q["id"], text or None, 1 if correct else 0))

            revealed = 1 if quiz["mode"] == "practice" else 0
            cur.execute(
                "INSERT INTO quiz_attempts (quiz_id, user_id, score, total, answers_revealed, "
                "submitted_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (quiz["id"], user_id, score, len(questions), revealed, utcnow()),
            )
            attempt_id = cur.lastrowid
            for question_id, text, is_correct in results:
                cur.execute(
                    "INSERT INTO quiz_answers (attempt_id, question_id, answer_text, is_correct) "
                    "VALUES (%s, %s, %s, %s)",
                    (attempt_id, question_id, text, is_correct),
                )
        conn.commit()
        return attempt_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reveal_attempt(attempt_id, user_id):
    """user_id in WHERE means nobody can reveal someone else's attempt."""
    execute("UPDATE quiz_attempts SET answers_revealed = 1 WHERE id = %s AND user_id = %s",
            (attempt_id, user_id))
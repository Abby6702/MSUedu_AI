"""Fictional demonstration data. Everything here is clearly fake: names say 'Sample',
emails are demo.*@example.com (a domain reserved for examples), and no password is
stored in the code (the command asks for one)."""
from datetime import timedelta

import click

from app import validators
from app.db import execute, query_all, query_one
from app.services import recommendation_service, tutor_service, user_service
from app.timeutil import local_to_utc, to_local, utcnow
from app.validators_tutor import parse_hhmm

EMAIL_PATTERN = "demo.%@example.com"
SESSION_TIME = ("14:00", "15:00")      # the sample Monday session (fits tutor1's Monday slot)

ACCOUNTS = [
    {"key": "student1", "name": "Sample Student A", "email": "demo.student1@example.com",
     "role": "student", "course": "BS Computer Science (sample)", "year": 2},
    {"key": "student2", "name": "Sample Student B", "email": "demo.student2@example.com",
     "role": "student", "course": "BS Mathematics (sample)", "year": 1},
    {"key": "tutor1", "name": "Sample Tutor One", "email": "demo.tutor1@example.com",
     "role": "tutor", "course": "BS Mathematics (sample)", "year": 4,
     "bio": "Sample biography for demonstration only. Enjoys explaining calculus step by step."},
    {"key": "tutor2", "name": "Sample Tutor Two", "email": "demo.tutor2@example.com",
     "role": "tutor", "course": "BS Physics (sample)", "year": 3,
     "bio": "Sample biography for demonstration only. Online sessions in science subjects."},
    {"key": "tutor3", "name": "Sample Tutor Three", "email": "demo.tutor3@example.com",
     "role": "tutor", "course": "BS Computer Science (sample)", "year": 3,
     "bio": "Sample biography for demonstration only. This profile is left PENDING so the "
            "administrator approval step can be demonstrated."},
]

# day 0 = Monday. tutor3 is deliberately not approved.
TUTOR_SETUP = {
    "tutor1": {"format": "both", "approved": True,
                "subjects": [("Calculus 1", "limits, derivatives"), ("College Algebra", "functions, equations"),
                               ("Python Programming", "loops, functions")],
               "slots": [(0, "13:00", "17:00"), (2, "09:00", "12:00")]},
    "tutor2": {"format": "online", "approved": True,
               "subjects": [("General Physics", "kinematics"), ("General Chemistry", "stoichiometry")],
               "slots": [(1, "15:00", "18:00"), (3, "15:00", "18:00")]},
    "tutor3": {"format": "in_person", "approved": False,
               "subjects": [("Programming Fundamentals", "loops, functions")],
               "slots": [(4, "10:00", "12:00")]},
}


def next_weekday(start, weekday):
    """The first date on or after `start` that falls on `weekday` (Monday = 0)."""
    return start + timedelta(days=(weekday - start.weekday()) % 7)


def _when(day, start, end):
    return local_to_utc(day.isoformat(), start), local_to_utc(day.isoformat(), end)

def _seed_learning(ids):
       """Sample lessons and quiz history for student 1, so the learning agent has measured data to decide
       from. Returns a note to show, or '' when everything was added."""
       student = ids["student1"]
       python = query_one("SELECT id FROM subjects WHERE name = 'Python Programming'")
       topic = (query_one("SELECT id FROM topics WHERE name = 'Functions' AND subject_id = %s", (python["id"],))
                if python else None)
       if not python or not topic:
           return ("Python lessons were not found, so no sample learning data was added. "
                   "Run: flask --app run init-db, then remove-demo and seed-demo again.")
       now = utcnow()
       lessons = query_all(
           "SELECT l.id FROM lessons l JOIN topics t ON t.id = l.topic_id "
           "WHERE t.subject_id = %s AND t.name IN ('Variables','Data Types','Input and Output','If and Else','Loops') "
           "ORDER BY t.level, t.position", (python["id"],))
       for days_ago, lesson in enumerate(reversed(lessons)):          # one lesson a day: a sample streak
           execute("INSERT IGNORE INTO lesson_progress (user_id, lesson_id, completed_at) VALUES (%s, %s, %s)",
                   (student, lesson["id"], now - timedelta(days=days_ago)))

       quiz_id = execute(
           "INSERT INTO quizzes (user_id, subject_id, topic_id, topic, difficulty, mode, question_count, created_at) "
           "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
           (student, python["id"], topic["id"], "Functions (sample quiz)", "easy", "practice", 4, now))
       questions = [("A function is defined with the def keyword.", "true"),
                    ("A function must always return a value.", "false"),
                    ("Parameters are the inputs a function receives.", "true"),
                    ("Calling a function runs its code.", "true")]
       question_ids = [execute(
           "INSERT INTO quiz_questions (quiz_id, position, q_type, question_text, options, correct_answer, "
           "accepted_answers, explanation) VALUES (%s, %s, 'tf', %s, NULL, %s, NULL, %s)",
           (quiz_id, position, text, correct, "Sample explanation (demonstration data)."))
           for position, (text, correct) in enumerate(questions, start=1)]
       for days_ago, correct_count in ((3, 4), (2, 3), (1, 1)):         # 100%, 75%, then 25%: a declining topic
           attempt_id = execute(
               "INSERT INTO quiz_attempts (quiz_id, user_id, score, total, answers_revealed, submitted_at) "
               "VALUES (%s, %s, %s, 4, 1, %s)", (quiz_id, student, correct_count, now - timedelta(days=days_ago)))
           for index, (question_id, (_text, correct)) in enumerate(zip(question_ids, questions)):
               right = index < correct_count
               given = correct if right else ("false" if correct == "true" else "true")
               execute("INSERT INTO quiz_answers (attempt_id, question_id, answer_text, is_correct) "
                       "VALUES (%s, %s, %s, %s)", (attempt_id, question_id, given, 1 if right else 0))
       try:
           recommendation_service.run_agent(student)                    # the agent decides from the data above
       except Exception:
           return "Sample data was added, but the learning agent could not run. Open the Recommendations page to run it."
       return ""
def _seed_sessions(ids, subjects):
    today = to_local(utcnow()).date()
    monday = next_weekday(today + timedelta(days=2), 0)
    wednesday = next_weekday(today + timedelta(days=2), 2)
    s1, s2, t1 = ids["student1"], ids["student2"], ids["tutor1"]
    insert = ("INSERT INTO tutoring_requests (student_id, tutor_id, subject_id, topic, description, "
              "session_format, start_at, end_at, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)")

    start, end = _when(monday - timedelta(days=14), *SESSION_TIME)          # a finished session
    done = execute(insert, (s1, t1, subjects["Calculus 1"], "Limits (sample session)",
                            "Sample data for demonstration.", "online", start, end, "completed"))
    start, end = _when(monday, *SESSION_TIME)                               # a confirmed, upcoming one
    execute(insert, (s1, t1, subjects["Calculus 1"], "Derivatives practice (sample)", None,
                     "online", start, end, "accepted"))
    start, end = _when(wednesday, "10:00", "11:00")                         # one waiting for the tutor
    execute(insert, (s2, t1, subjects["College Algebra"], "Solving equations (sample)",
                     "Sample data for demonstration.", "online", start, end, "pending"))

    execute("INSERT INTO session_records (request_id, tutor_id, topics_covered, outcomes, next_steps, "
            "summary_text, summary_ai_assisted, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (done, t1, "Limits and limit laws (sample)",
             "Sample record: practised evaluating simple limits.",
             "Sample next step: try derivative exercises.", None, 0, utcnow()))
    execute("INSERT INTO feedback (request_id, student_id, tutor_id, rating, comment, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (done, s1, t1, 5, "Sample feedback: the explanations were clear.", utcnow()))


def seed(password):
    """Create all sample data. Returns {key: user_id}."""
    if query_one("SELECT COUNT(*) AS n FROM users WHERE email LIKE %s", (EMAIL_PATTERN,))["n"]:
        raise click.ClickException("Sample accounts already exist. Run remove-demo first.")
    subjects = {r["name"]: r["id"] for r in query_all("SELECT id, name FROM subjects WHERE is_active = 1")}
    needed = {name for setup in TUTOR_SETUP.values() for name, _ in setup["subjects"]}
    missing = sorted(needed - set(subjects))
    if missing:
        raise click.ClickException("These starter subjects are missing or inactive: "
                                   + ", ".join(missing) + ". Activate them in Admin > Subjects.")

    ids = {}
    for acct in ACCOUNTS:
        uid = user_service.create_user(acct["name"], acct["email"], password, acct["role"])
        ids[acct["key"]] = uid
        profile = {"full_name": acct["name"], "course": acct["course"], "year_level": acct["year"]}
        if acct["role"] == "student":
            profile["learning_goals"] = "Sample learning goals (demonstration data)."
        else:
            profile.update({"student_number": "", "bio": acct["bio"]})
        user_service.update_profile(uid, acct["role"], profile)

    for key, setup in TUTOR_SETUP.items():
        uid = ids[key]
        tutor_service.save_teaching_setup(
            uid, setup["format"], [(subjects[name], topics) for name, topics in setup["subjects"]])
        for day, start, end in setup["slots"]:
            problem = tutor_service.add_slot(uid, day, parse_hhmm(start), parse_hhmm(end))
            if problem:
                raise click.ClickException(problem)
        if setup["approved"]:
            execute("UPDATE tutor_profiles SET approval_status = 'approved', reviewed_at = NOW() "
                    "WHERE user_id = %s", (uid,))

    _seed_sessions(ids, subjects)
    note = _seed_learning(ids)
    if note:
           click.echo(note)
    user_service.log_audit(None, "demo_data_seeded", None, None, f"{len(ids)} sample accounts")
    return ids


def remove():
    """Delete the sample students and tutors (their sessions, feedback, etc. go with them).
    Returns how many accounts were removed."""
    params = (EMAIL_PATTERN,)
    where = "email LIKE %s AND role IN ('student', 'tutor')"
    count = query_one(f"SELECT COUNT(*) AS n FROM users WHERE {where}", params)["n"]
    if count:
        execute(f"DELETE FROM users WHERE {where}", params)
        user_service.log_audit(None, "demo_data_removed", None, None, f"{count} sample accounts")
    return count


def register_commands(app):
    @app.cli.command("seed-demo")
    def seed_demo_command():
        """Create FICTIONAL sample accounts and sessions for a demonstration."""
        click.echo("This creates fictional accounts (demo.*@example.com) with sample data.")
        password = click.prompt("Choose ONE password for all sample accounts",
                                hide_input=True, confirmation_prompt=True)
        problems = validators.password_errors(password)
        if problems:
            for problem in problems:
                click.echo(f"  - {problem}")
            raise SystemExit(1)
        seed(password)
        click.echo("Done. Log in with the password you just chose:")
        for acct in ACCOUNTS:
            click.echo(f"  {acct['role']:8} {acct['email']}")
        click.echo("Tutor Three is left PENDING on purpose. Create your own administrator with: "
                   "flask --app run create-admin")

    @app.cli.command("remove-demo")
    def remove_demo_command():
        """Delete the fictional sample accounts and everything linked to them."""
        if not click.confirm("Delete all demo.*@example.com accounts and their data?"):
            raise SystemExit(0)
        click.echo(f"Removed {remove()} sample account(s).")
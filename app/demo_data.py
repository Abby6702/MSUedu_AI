"""Fictional demonstration data. Everything here is clearly fake: names say 'Sample',
emails are demo.*@example.com (a domain reserved for examples), and no password is
stored in the code (the command asks for one)."""
from datetime import timedelta

import click

from app import validators
from app.db import execute, query_all, query_one
from app.services import tutor_service, user_service
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
               "subjects": [("Calculus 1", "limits, derivatives"), ("College Algebra", "functions, equations")],
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
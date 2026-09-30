"""Server-side input checks. The browser also checks, but the server must never
trust the browser, so every rule is enforced here."""
import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
STUDENT_NO_RE = re.compile(r"^[A-Za-z0-9-]{3,30}$")
YEAR_LEVELS = {"1", "2", "3", "4", "5", "6"}


def clean(text):
    """Trim and collapse repeated spaces."""
    return " ".join((text or "").split())


def email_error(email):
    if len(email) > 255 or not EMAIL_RE.match(email):
        return "Enter a valid email address."
    return None


def password_errors(password):
    errors = []
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if len(password) > 128:
        errors.append("Password must be at most 128 characters.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        errors.append("Password needs at least one letter and one number.")
    return errors


def validate_registration(form):
    """Returns (cleaned_data, list_of_errors). Passwords are never returned."""
    data = {
        "full_name": clean(form.get("full_name")),
        "email": (form.get("email") or "").strip().lower(),
        "role": form.get("role") or "",
    }
    password = form.get("password") or ""
    errors = []

    if not 2 <= len(data["full_name"]) <= 100:
        errors.append("Full name must be 2 to 100 characters.")
    problem = email_error(data["email"])
    if problem:
        errors.append(problem)
    if data["role"] not in ("student", "tutor"):   # admin can NEVER self-register
        errors.append("Choose whether you are a student or a tutor.")
    errors += password_errors(password)
    if password != (form.get("confirm_password") or ""):
        errors.append("The two passwords do not match.")
    return data, errors


def validate_profile(form, role):
    errors = []
    data = {"full_name": clean(form.get("full_name"))}
    if not 2 <= len(data["full_name"]) <= 100:
        errors.append("Full name must be 2 to 100 characters.")

    if role in ("student", "tutor"):
        data["course"] = clean(form.get("course"))
        if not 2 <= len(data["course"]) <= 100:
            errors.append("Course is required (2 to 100 characters).")
        raw_year = (form.get("year_level") or "").strip()
        if raw_year in YEAR_LEVELS:
            data["year_level"] = int(raw_year)
        else:
            data["year_level"] = raw_year
            errors.append("Choose a valid year level (1 to 6).")

    if role == "student":
        data["learning_goals"] = (form.get("learning_goals") or "").strip()
        if len(data["learning_goals"]) > 500:
            errors.append("Learning goals must be 500 characters or fewer.")

    if role == "tutor":
        data["student_number"] = clean(form.get("student_number"))
        if data["student_number"] and not STUDENT_NO_RE.match(data["student_number"]):
            errors.append("Student number may use letters, numbers and dashes (3 to 30 characters).")
        data["bio"] = (form.get("bio") or "").strip()
        if len(data["bio"]) > 1000:
            errors.append("Bio must be 1000 characters or fewer.")
    return data, errors
"""Server-side checks for the tutor details form."""
import re
from app.validators import clean

MAX_SKILLS = 10
MAX_SKILL_LENGTH = 40


def parse_skills(text):
    """'Python, python ,Calculus' -> ['Python', 'Calculus'] (trimmed, no empties, no repeats)."""
    seen, skills = set(), []
    for part in re.split(r"[,\n]", text or ""):
        skill = clean(part)
        if skill and skill.lower() not in seen:
            seen.add(skill.lower())
            skills.append(skill)
    return skills


def validate_details(form):
    """Returns (data, errors). data['skills'] is a ', ' joined string ready to store."""
    errors = []
    skills = parse_skills(form.get("skills"))
    if len(skills) > MAX_SKILLS:
        errors.append(f"List at most {MAX_SKILLS} skills.")
    if any(len(s) > MAX_SKILL_LENGTH for s in skills):
        errors.append(f"Each skill must be {MAX_SKILL_LENGTH} characters or fewer.")

    education = clean(form.get("education"))
    if len(education) > 300:
        errors.append("Education must be 300 characters or fewer.")
    experience = (form.get("experience") or "").strip()
    if len(experience) > 1000:
        errors.append("Experience must be 1000 characters or fewer.")

    return {"skills": ", ".join(skills), "education": education, "experience": experience}, errors
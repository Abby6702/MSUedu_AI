"""The learning agent's DECISIONS. Pure functions (no database, no AI model, no network),
so every rule is easy to test and easy to explain. Input: quiz results per topic and lesson
completion. Output: recommendations, each with structured reasoning."""
from app.services import profile_service

WEAK_MAX = profile_service.WEAK_MAX          # below this percent = weak (60)
TUTOR_AFTER_WEAK_RUN = 3                     # weak quizzes in a row, after the review is done
TUTOR_ANYWAY_RUN = 5                         # weak quizzes in a row, even without finishing the review
PRIORITY = {"human_tutor": 0, "review_lesson": 1, "practice": 2, "next_lesson": 3}
NO_LESSONS = {"total": 0, "done": 0, "next": None}


def trailing_weak(percents):
    """How many of the most recent scores in a row are below the weak limit."""
    run = 0
    for p in reversed(percents):
        if p >= WEAK_MAX:
            break
        run += 1
    return run


def recommend_difficulty(latest):
    if latest < 50:
        return "easy"
    return "medium" if latest < 75 else "hard"


def index_lessons(rows):
    """Rows (ordered by level, position, lesson) -> (by_topic, by_subject) completion summaries."""
    by_topic, by_subject = {}, {}
    for r in rows:
        t = by_topic.setdefault(r["topic_id"], {"total": 0, "done": 0, "next": None})
        s = by_subject.setdefault(r["subject_id"], {"name": r["subject_name"], "total": 0,
                                                    "done": 0, "next": None})
        done = bool(r["completed"])
        for box in (t, s):
            box["total"] += 1
            box["done"] += done
            if not done and box["next"] is None:
                box["next"] = {"id": r["lesson_id"], "title": r["title"], "topic": r["topic_name"]}
    return by_topic, by_subject


def _steps(t, lessons, run):
    scores = ", ".join(f"{p}%" for p in t["percents"])
    steps = [f"Quiz results on {t['topic_name']}: {scores} (average {t['average']}%, latest {t['latest']}%)."]
    if t["status"] == "weak":
        steps.append(f"The average or the latest score is below {WEAK_MAX}%, so this topic is classed as needs work.")
    else:
        steps.append("Scores are between the weak and strong limits, so this topic is classed as developing.")
    if lessons["total"]:
        steps.append(f"Lessons finished for this topic: {lessons['done']} of {lessons['total']}.")
    else:
        steps.append("This topic has no lessons in the learning path, so there is nothing to review first.")
    if run:
        plural = "scores are" if run > 1 else "score is"
        steps.append(f"Your last {run} quiz {plural} below {WEAK_MAX}%.")
    return steps


def _rec(t, kind, rule, title, message, steps, lesson_id=None, difficulty=None, lessons=NO_LESSONS, run=0):
    return {"key": f"t{t['topic_id']}", "kind": kind, "topic_id": t["topic_id"],
            "subject_id": t["subject_id"], "lesson_id": lesson_id, "difficulty": difficulty,
            "title": title[:200], "message": message[:500],
            "evidence": t["attempts"] + lessons["done"],
            "reasoning": {"rule": rule,
                          "facts": {"topic": t["topic_name"], "scores": t["percents"],
                                    "average": t["average"], "latest": t["latest"],
                                    "status": t["status"], "weak_run": run,
                                    "lessons_done": lessons["done"], "lessons_total": lessons["total"]},
                          "steps": steps}}


def decide_topic(t, lessons):
    """One topic summary -> one recommendation, or None."""
    if t["status"] == "strong":
        return None
    if t["status"] == "developing" and t["attempts"] < 2:
        return None                                    # one quiz is too little evidence
    lessons = lessons or NO_LESSONS
    run = trailing_weak(t["percents"])
    review_done = lessons["done"] >= lessons["total"]  # also true when the topic has no lessons
    steps = _steps(t, lessons, run)
    name, weak = t["topic_name"], t["status"] == "weak"

    if weak and (run >= TUTOR_ANYWAY_RUN or (review_done and run >= TUTOR_AFTER_WEAK_RUN)):
        steps.append("The weakness has continued over several attempts, so extra help from a person may be useful. "
                     "This is a suggestion, not a diagnosis.")
        return _rec(t, "human_tutor", "R4_human_tutor", f"Consider a student tutor for {name}",
                    f"Your last {run} quiz scores on {name} were below {WEAK_MAX}%. A student tutor can "
                    "explain it in person. This is a suggestion, not a diagnosis.",
                    steps, lessons=lessons, run=run)
    if not review_done:
        nxt = lessons["next"]
        steps.append(f"Not every lesson is finished, so the next step is to review: {nxt['title']}.")
        return _rec(t, "review_lesson", "R1_review", f"Review: {nxt['title']}",
                    f"Your quiz results on {name} suggest reviewing this lesson before more quizzes.",
                    steps, lesson_id=nxt["id"], lessons=lessons, run=run)
    level = recommend_difficulty(t["latest"]) if weak else "medium"
    steps.append(f"The lessons are finished but the results are still not strong, so more practice at "
                 f"{level} difficulty is next.")
    return _rec(t, "practice", "R2_practice", f"Practice {name} ({level})",
                f"Try another {level} quiz on {name} to check your progress.",
                steps, difficulty=level, lessons=lessons, run=run)


def decide_all(topics, by_topic, by_subject):
    """All recommendations for one student, most urgent first."""
    desired, weak_subjects = [], set()
    for t in topics:
        if t["status"] == "weak":
            weak_subjects.add(t["subject_id"])
        rec = decide_topic(t, by_topic.get(t["topic_id"]))
        if rec:
            desired.append(rec)
    for subject_id, s in by_subject.items():
        if not s["done"] or s["next"] is None or subject_id in weak_subjects:
            continue
        nxt = s["next"]
        desired.append({
            "key": f"s{subject_id}", "kind": "next_lesson", "topic_id": None, "subject_id": subject_id,
            "lesson_id": nxt["id"], "difficulty": None, "title": f"Next lesson: {nxt['title']}"[:200],
            "message": f"Continue {s['name']} with the next lesson on your path.", "evidence": s["done"],
            "reasoning": {"rule": "NEXT_lesson",
                          "facts": {"subject": s["name"], "lessons_done": s["done"], "lessons_total": s["total"]},
                          "steps": [f"You have finished {s['done']} of {s['total']} lessons in {s['name']}.",
                                    "No topic in this subject is currently classed as needs work, so the "
                                    "path continues with the next unfinished lesson."]}})
    return sorted(desired, key=lambda d: (PRIORITY[d["kind"]], d["title"]))


def plan_sync(existing, desired):
    """Compare stored recommendations with the new decisions.
    existing: {key: {"id", "kind", "status", "evidence"}} for live (active or dismissed) ones.
    Returns {"retire": [(id, new_status)], "update": [(id, rec)], "insert": [rec]}."""
    plan = {"retire": [], "update": [], "insert": []}
    wanted = {d["key"]: d for d in desired}
    for key, d in wanted.items():
        e = existing.get(key)
        if e is None:
            plan["insert"].append(d)
        elif e["status"] == "dismissed":
            if e["kind"] == d["kind"] and e["evidence"] == d["evidence"]:
                continue                                  # dismissed, and nothing new has happened
            plan["retire"].append((e["id"], "superseded"))
            plan["insert"].append(d)
        elif e["kind"] == d["kind"]:
            plan["update"].append((e["id"], d))
        else:
            plan["retire"].append((e["id"], "superseded"))
            plan["insert"].append(d)
    for key, e in existing.items():
        if key not in wanted:
            plan["retire"].append((e["id"], "done" if e["status"] == "active" else "superseded"))
    return plan
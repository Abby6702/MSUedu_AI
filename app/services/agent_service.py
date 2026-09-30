"""The coordinator: PLAN (AI) -> ACT (Python tools) -> EXPLAIN (Python) -> CONFIRM (student)."""
import secrets
import time
from datetime import datetime

from flask import current_app

from app.ai import agent_logic, agent_prompts, ollama_client
from app.services import agent_tools, ai_service, tutor_service, user_service
from app.services import request_service as rs
from app.timeutil import to_local, utcnow
from app.validators_request import DURATIONS

PLAN_FAILED = ("I could not work out what you want. Please rephrase, for example: "
               "\"I need help with Calculus 1 on Monday afternoon\".")
TOOL_FAILED = "The coordinator could not finish that. Please try again."
HELP_TEXT = ("I can help you: (1) find a tutor and real open times, (2) check the status of "
             "your requests, (3) cancel a request or session, and (4) look for a new time with "
             "the same tutor. I can never accept requests for a tutor, and I never change "
             "anything until you press Confirm.")
INTENT_LABELS = {"find_tutor": "you want to find a tutor and open times",
                 "reschedule": "you want to move an existing session",
                 "cancel": "you want to cancel a request or session",
                 "status": "you want to know where your requests stand",
                 "other": "your message is not about tutoring requests"}


def _new_ctx(user_id):
    return {"user_id": user_id, "role": "student", "run_id": secrets.token_hex(8), "steps": []}


def _reply(text, **extra):
    return {"reply": text, **extra}


# ---------- step 2: what to do for each kind of plan ----------
def _suggest(ctx, intent, subject, topic, fmt, tutor_id=None, duration=None, note=""):
    today = to_local(utcnow()).date()
    dates, problem = agent_logic.resolve_days(intent["day"], today)
    if problem:
        return _reply(problem)

    matches = agent_tools.run_tool(ctx, "find_tutors", subject_id=subject["id"], format=fmt)
    if tutor_id is not None:
        matches = [m for m in matches if m["tutor"]["id"] == tutor_id]
    if not matches:
        return _reply(f"{note}No approved tutor currently teaches {subject['name']}"
                      + (" in that format" if fmt else "") + ".")

    duration = duration or intent["duration"]
    wording = agent_logic.describe_preferences(intent, tutor_service.fmt_time)
    suggestions = []
    for m in matches[:5]:
        tutor = m["tutor"]
        slots = agent_tools.run_tool(
            ctx, "get_open_slots", tutor_id=tutor["id"], dates=dates, duration=duration,
            time_pref=intent["time"], part_of_day=intent["part_of_day"])
        if slots:
            own_format = fmt or ("online" if tutor["tutoring_format"] in ("online", "both")
                                 else "in_person")
            suggestions.append({"tutor_id": tutor["id"], "tutor_name": tutor["full_name"],
                                "course": tutor["course"] or "", "format": own_format,
                                "format_label": tutor_service.FORMAT_LABELS[own_format],
                                "why": m["reasons"], "slots": slots})
        if len(suggestions) == 3:
            break

    if not suggestions:
        names = ", ".join(m["tutor"]["full_name"] for m in matches[:5])
        return _reply(f"{note}{len(matches)} tutor(s) teach {subject['name']} ({names}), but none "
                      f"of them have open times {wording}. Try another day or time, or leave "
                      "the day out to search the next two weeks.")

    # Prepare (NOT send) a request for the first option.
    first = suggestions[0]
    prepared = agent_tools.run_tool(
        ctx, "prepare_request", tutor_id=first["tutor_id"], subject_id=subject["id"],
        topic=topic, format=first["format"], start=first["slots"][0]["start"], duration=duration)
    proposals = [prepared["proposal"]] if prepared["ok"] else []

    text = (f"{note}I found {len(suggestions)} tutor{'s' if len(suggestions) != 1 else ''} for "
            f"{subject['name']} with open times {wording}. These times come from each tutor's "
            "saved weekly availability minus confirmed sessions (yours and theirs), so they are "
            "real openings. ")
    if proposals:
        text += ("I prepared a request for the first option below. Nothing is sent until you "
                 "press Confirm. To choose a different time, click it in the list.")
    else:
        text += ("Click a time to prepare a request. Nothing is sent until you confirm. "
                 f"(I could not prepare the first option: {prepared['problem']})")

    for s in suggestions:                      # JSON-friendly: no datetime objects
        s["slots"] = [{"start_iso": x["start_iso"], "label": x["label"]} for x in s["slots"]]
    return _reply(text, suggestions=suggestions, proposals=proposals,
                  context={"subject_id": subject["id"], "topic": topic, "duration": duration})


def _h_find(ctx, intent, message):
    subjects = agent_tools.run_tool(ctx, "list_subjects")
    subject = (agent_logic.match_subject(intent["subject"], subjects)
               or agent_logic.find_subject_in_message(message, subjects))
    if subject is None:
        names = ", ".join(s["name"] for s in subjects) or "none yet"
        return _reply("Which subject do you need help with? Subjects on the platform: "
                      f"{names}.")
    return _suggest(ctx, intent, subject, intent["topic"] or subject["name"], intent["format"])


def _choose_request(ctx, intent, message, subjects):
    """Find the ONE request the student means. Returns (request, None) or (None, reply)."""
    groups = agent_tools.run_tool(ctx, "get_my_requests")
    cands = [r for r in groups["attention"] + groups["upcoming"] if "cancel" in r["actions"]]

    wanted_id = agent_logic.extract_request_id(message)
    if wanted_id is not None:
        cands = [r for r in cands if r["id"] == wanted_id]
    else:
        subject = (agent_logic.match_subject(intent["subject"], subjects)
                   or agent_logic.find_subject_in_message(message, subjects))
        if subject:
            cands = [r for r in cands if r["subject_name"] == subject["name"]]
        named = [r for r in cands
                 if agent_logic.normalize(r["tutor_name"]) in agent_logic.normalize(message)]
        cands = named or cands

    if not cands:
        return None, _reply("I could not find an open request or upcoming session that matches. "
                            "Tell me its number (for example #12) or open My requests.")
    if len(cands) > 1:
        lines = "\n".join("- " + agent_logic.describe_request(r) for r in cands)
        return None, _reply("More than one request could match:\n" + lines +
                            "\nTell me which one by its number, for example: \"cancel #12\".")
    return cands[0], None


def _h_cancel(ctx, intent, message):
    subjects = agent_tools.run_tool(ctx, "list_subjects")
    req, early = _choose_request(ctx, intent, message, subjects)
    if early:
        return early
    result = agent_tools.run_tool(ctx, "prepare_cancel", request_id=req["id"])
    if not result["ok"]:
        return _reply(f"I could not prepare that cancellation: {result['problem']}")
    return _reply("I prepared the cancellation below. Nothing changes until you press Confirm.",
                  proposals=[result["proposal"]])


def _h_reschedule(ctx, intent, message):
    subjects = agent_tools.run_tool(ctx, "list_subjects")
    req, early = _choose_request(ctx, intent, message, subjects)
    if early:
        return early
    subject = next((s for s in subjects if s["name"] == req["subject_name"]), None)
    if subject is None:
        return _reply("That subject is no longer active, so I cannot look for new times.")
    minutes = int((req["end_at"] - req["start_at"]).total_seconds() // 60)
    note = (f"To move #{req['id']}, I looked for new times with the same tutor. Your current "
            "booking stays until you cancel it, and the tutor must accept the new request. ")
    return _suggest(ctx, intent, subject, req["topic"], req["session_format"],
                    tutor_id=req["tutor_id"],
                    duration=minutes if minutes in DURATIONS else None, note=note)


def _h_status(ctx, intent, message):
    groups = agent_tools.run_tool(ctx, "get_my_requests")
    current = [agent_logic.describe_request(r) for r in groups["attention"] + groups["upcoming"]]
    recent = [agent_logic.describe_request(r) for r in groups["history"][:3]]
    if not current and not recent:
        return _reply("You have no requests or sessions yet. Ask me to find you a tutor!")
    parts = []
    if current:
        parts.append("Open requests and upcoming sessions:\n" + "\n".join("- " + c for c in current))
    else:
        parts.append("You have no open requests or upcoming sessions.")
    if recent:
        parts.append("Most recent finished ones:\n" + "\n".join("- " + c for c in recent))
    parts.append("I never change anything for you without your confirmation. "
                 "Use My requests to act on a proposed new time.")
    return _reply("\n\n".join(parts))


def _h_other(ctx, intent, message):
    return _reply(HELP_TEXT)


HANDLERS = {"find_tutor": _h_find, "reschedule": _h_reschedule, "cancel": _h_cancel,
            "status": _h_status, "other": _h_other}


# ---------- the whole run ----------
def run_agent(user_id, message):
    """Returns (http_status, json_body)."""
    if ai_service._rate_limited(user_id):
        return 429, {"ok": False, "error": "You have sent a lot of requests. "
                                           "Please wait a few minutes and try again."}
    started = time.monotonic()
    ctx = _new_ctx(user_id)

    # ---- Step 1: PLAN. The only place the AI model is used. ----
    now_local = to_local(utcnow())
    today_text = f"Today is {now_local:%A}, {now_local:%Y-%m-%d} (Philippine time)."
    try:
        raw = ollama_client.chat(
            [{"role": "system", "content": agent_prompts.SYSTEM},
             {"role": "user", "content": agent_prompts.build_user_prompt(message, today_text)}],
            temperature=0.1, json_mode=True, max_tokens=300)
    except ollama_client.OllamaError as error:
        ai_service._log_usage(user_id, "agent", None, False, error.code, started)
        return (ai_service.STATUS_CODES.get(error.code, 502),
                {"ok": False, "error": ai_service.ERROR_MESSAGES.get(
                    error.code, ai_service.ERROR_MESSAGES["error"])})
    except Exception:
        current_app.logger.exception("Unexpected error in the agent planning step")
        ai_service._log_usage(user_id, "agent", None, False, "error", started)
        return 502, {"ok": False, "error": ai_service.ERROR_MESSAGES["error"]}

    intent = agent_logic.parse_intent(raw)
    if intent is None:
        agent_tools.log_step(ctx, "plan", None, False, "unreadable_plan")
        ai_service._log_usage(user_id, "agent", None, False, "bad_format", started)
        return 502, {"ok": False, "error": PLAN_FAILED}
    agent_tools.log_step(ctx, "plan", None, True, f"intent={intent['intent']}")
    ctx["steps"].append({"kind": "plan",
                         "text": f"Understood your message as: {INTENT_LABELS[intent['intent']]}"})

    # ---- Step 2 and 3: ACT with checked tools, EXPLAIN from real data ----
    try:
        body = HANDLERS[intent["intent"]](ctx, intent, message)
    except Exception:
        current_app.logger.exception("The agent could not complete its steps")
        ai_service._log_usage(user_id, "agent", None, False, "tool_error", started)
        return 500, {"ok": False, "error": TOOL_FAILED}

    body["ok"] = True
    body["steps"] = ctx["steps"]
    ai_service._log_usage(user_id, "agent", None, True, None, started)
    return 200, body


def prepare_choice(user_id, tutor_id, subject_id, topic, fmt, start, duration):
    """The student clicked a time in the list. Validate again and prepare (NOT send)."""
    ctx = _new_ctx(user_id)
    try:
        result = agent_tools.run_tool(ctx, "prepare_request", tutor_id=tutor_id,
                                      subject_id=subject_id, topic=topic, format=fmt,
                                      start=start, duration=duration)
    except agent_tools.ToolError:
        return 400, {"ok": False, "error": "That choice is not valid. Please ask again."}
    if not result["ok"]:
        return 409, {"ok": False, "error": result["problem"]}
    return 200, {"ok": True, "proposal": result["proposal"]}


# ---------- step 4: CONFIRM (only ever called from a button click) ----------
def confirm_proposal(user_id, proposal_id):
    ctx = _new_ctx(user_id)
    proposal = agent_tools.load_proposal(proposal_id, user_id)
    if proposal is None or not proposal["payload"]:
        return 404, {"ok": False, "error": "Proposal not found."}
    if proposal["status"] != "prepared":
        return 409, {"ok": False, "error": "This proposal was already handled."}
    if proposal["expires_at"] <= utcnow():
        agent_tools.set_status(proposal_id, user_id, "expired")
        return 410, {"ok": False, "error": "This proposal expired. Please ask me again."}
    if not agent_tools.claim_proposal(proposal_id, user_id):
        return 409, {"ok": False, "error": "This proposal was already handled or has expired."}

    data = proposal["payload"]["data"]
    try:
        if proposal["kind"] == "request":
            request_data = {"subject_id": data["subject_id"], "topic": data["topic"],
                            "description": "", "format": data["format"],
                            "start": datetime.fromisoformat(data["start"]),
                            "end": datetime.fromisoformat(data["end"])}
            # The REAL create: every check runs again, because things may have changed.
            target_id, problem = rs.create_request(user_id, data["tutor_id"], request_data)
            ok = problem is None
            message = "Request sent. The tutor will reply soon." if ok else problem
            audit = "agent_request_confirmed"
        else:
            target_id = data["request_id"]
            ok, message = rs.perform_action(target_id, user_id, "cancel")
            audit = "agent_cancel_confirmed"
    except Exception:
        current_app.logger.exception("Confirming an agent proposal failed")
        agent_tools.set_status(proposal_id, user_id, "prepared")    # let them retry
        agent_tools.log_step(ctx, "confirm", None, False, f"proposal={proposal_id} error")
        return 500, {"ok": False, "error": "Something went wrong. Please try again."}

    agent_tools.log_step(ctx, "confirm", None, ok, f"proposal={proposal_id}")
    if not ok:
        agent_tools.set_status(proposal_id, user_id, "discarded")
        return 409, {"ok": False, "error": message}
    try:
        user_service.log_audit(user_id, audit, "request", target_id)
    except Exception:
        current_app.logger.exception("Could not write the audit log")
    return 200, {"ok": True, "message": message}


def discard(user_id, proposal_id):
    if agent_tools.discard_proposal(proposal_id, user_id):
        return 200, {"ok": True, "message": "Discarded. Nothing was changed."}
    return 409, {"ok": False, "error": "This proposal was already handled or does not exist."}
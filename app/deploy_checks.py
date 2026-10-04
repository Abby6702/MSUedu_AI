"""Pure helpers for setting up and checking a deployment (no database, no Flask)."""
import re

EXPECTED_TABLES = (
    "agent_action_logs", "agent_proposals", "ai_conversations", "ai_messages", "ai_usage_logs",
    "audit_logs", "feedback", "lesson_progress", "lessons", "login_attempts",
    "notification_preferences", "notifications", "platform_settings", "quiz_answers", "quiz_attempts",
    "quiz_questions", "quizzes", "recommendations", "session_files", "session_messages",
    "session_records", "session_summaries", "student_profiles", "subjects", "topics",
    "tutor_availability", "tutor_profiles", "tutor_subjects", "tutoring_requests", "users")

# Columns added later with ALTER TABLE: if the tables exist but these do not, a script was skipped.
EXPECTED_COLUMNS = (
    ("users", "must_change_password"), ("users", "session_version"),
    ("tutor_profiles", "tutoring_format"), ("tutor_profiles", "skills"), ("tutor_profiles", "photo_filename"),
    ("student_profiles", "share_progress_with_tutors"), ("quizzes", "topic_id"))

# MySQL errors that only mean "this change is already in place":
#   1050 table exists, 1060 duplicate column, 1061 duplicate key name, 1826 duplicate foreign key name
IGNORABLE_ERRORS = {1050, 1060, 1061, 1826}

SCHEMA_NAME = re.compile(r"^schema_phase(\d+)\.sql$")
PLACEHOLDER = re.compile(r"replace|change|example|secret-key|test", re.IGNORECASE)
ORIGIN = re.compile(r"^https?://[A-Za-z0-9.-]+(:\d{1,5})?$")


def split_sql(text):
    """Split a .sql file into statements. Semicolons and '--' inside quoted text are respected,
    and '--' comments are dropped."""
    statements, current, quote, i, n = [], [], None, 0, len(text)
    while i < n:
        ch = text[i]
        if quote:
            current.append(ch)
            if ch == "\\" and i + 1 < n:                     # an escaped character inside a string
                current.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                if i + 1 < n and text[i + 1] == quote:        # a doubled quote ('') stays inside the string
                    current.append(text[i + 1])
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            current.append(ch)
        elif ch == "-" and text.startswith("--", i):
            end = text.find("\n", i)
            i = n if end == -1 else end                       # skip the comment, keep the line break
            continue
        elif ch == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def order_schema_files(names):
    """schema_phase2.sql ... schema_phase18.sql in NUMERIC order. Other files are ignored."""
    found = []
    for name in names:
        match = SCHEMA_NAME.match(name)
        if match:
            found.append((int(match.group(1)), name))
    return [name for _number, name in sorted(found)]


def missing_schema(tables_present, columns_present):
    tables = [t for t in EXPECTED_TABLES if t not in tables_present]
    columns = [f"{t}.{c}" for t, c in EXPECTED_COLUMNS if (t, c) not in columns_present]
    return tables, columns


def parse_origins(text):
    """SOCKETIO_ORIGINS='https://a.example, https://b.example' -> a list, or None (same-origin only).
    A wildcard is deliberately not accepted."""
    items = [o.strip().rstrip("/") for o in (text or "").split(",") if o.strip()]
    good = [o for o in items if ORIGIN.match(o)]
    return good or None


def check_settings(cfg, debug=False, trust_proxy=False):
    """Review settings before going live. Returns [(level, message)] with level in
    ok, info, warn or error. `cfg` is a dict-like (the Flask config)."""
    out = []

    def add(level, text):
        out.append((level, text))

    key = cfg.get("SECRET_KEY") or ""
    if len(key) < 32 or PLACEHOLDER.search(key):
        add("error", "SECRET_KEY is short or looks like a placeholder. Generate one with: "
                     "python -c \"import secrets; print(secrets.token_hex(32))\"")
    else:
        add("ok", "SECRET_KEY looks strong.")

    if debug:
        add("error", "APP_DEBUG is on. Debug mode includes a debugger that can run code. Set APP_DEBUG=false.")
    else:
        add("ok", "Debug mode is off.")

    if not cfg.get("SESSION_COOKIE_SECURE"):
        add("error", "SESSION_COOKIE_SECURE is off. Serve the site over HTTPS and set SESSION_COOKIE_SECURE=true.")
    else:
        add("ok", "Session cookies are HTTPS-only.")

    if cfg.get("CSP_ENABLED") is False:
        add("error", "CSP_ENABLED is off. Turn the Content-Security-Policy back on.")
    else:
        add("ok", "Content-Security-Policy is on.")

    if (cfg.get("DB_USER") or "").lower() == "root":
        add("error", "The app connects to MySQL as root. Use a dedicated account limited to the app's database.")
    elif not cfg.get("DB_USER"):
        add("error", "DB_USER is not set.")
    else:
        add("ok", "The app uses its own database account.")
    if not cfg.get("DB_PASSWORD"):
        add("error", "DB_PASSWORD is empty.")

    if cfg.get("SHOW_SYSTEM_STATUS"):
        add("warn", "SHOW_SYSTEM_STATUS is on, so the home page shows database status. Set it to false.")

    provider = cfg.get("AI_PROVIDER", "ollama")
    if provider == "openai":
        if not (cfg.get("AI_API_KEY") and cfg.get("AI_MODEL")):
            add("error", "AI_PROVIDER=openai but AI_API_KEY or AI_MODEL is missing.")
        else:
            add("ok", "An online AI provider is configured.")
        if not str(cfg.get("AI_BASE_URL", "")).lower().startswith("https://"):
            add("warn", "AI_BASE_URL is not https, so the API key would travel unencrypted.")
        add("info", "Online AI: questions and lesson text are sent to that provider. The About page says so.")
    elif provider == "ollama":
        add("warn", "AI uses Ollama on the same machine. Most cloud hosts cannot run it. Use AI_PROVIDER=openai, "
                    "or point OLLAMA_BASE_URL at a private machine that runs Ollama.")
    else:
        add("error", f"AI_PROVIDER '{provider}' is not recognised (use ollama or openai).")

    if not (cfg.get("TURN_URLS") and cfg.get("TURN_USERNAME") and cfg.get("TURN_CREDENTIAL")):
        add("warn", "No TURN relay is configured, so live video can fail between some networks.")

    if not trust_proxy:
        add("warn", "TRUST_PROXY is off. Behind a reverse proxy, turn it on (only when exactly ONE proxy is in "
                    "front) so visitor IPs and HTTPS are read correctly.")
    if cfg.get("REMINDERS_ENABLED"):
        add("info", "Reminders run inside the web process: set START_SCHEDULER=true on exactly one instance.")
    add("info", "Uploaded files need a persistent disk (UPLOAD_FOLDER). Back it up with the database.")
    return out


def has_errors(results):
    return any(level == "error" for level, _text in results)
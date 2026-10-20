"""Run with:  python -m pytest -v
Final review tests: every POST route needs a CSRF token, no secrets in the code, the SQL files and the
expected tables agree, the setup commands behave, and the documentation matches the code."""
import re
from pathlib import Path

import pymysql
import pytest

from app import create_app, demo_data, deploy_checks as dc, ops
from app.routes import main as main_routes
from app.services import mail_service
from config import Config

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"venv", ".git", "tests", "uploads", "backups", "__pycache__", "node_modules", ".pytest_cache"}


class P20Config(Config):
    TESTING = True
    SECRET_KEY = "test-only-not-a-real-secret"
    WTF_CSRF_ENABLED = False


class CsrfOnConfig(Config):
    TESTING = True
    SECRET_KEY = "test-only-not-a-real-secret"       # CSRF protection stays ON (Flask-WTF default)


class GoodConfig(Config):
    TESTING = True
    SECRET_KEY = "a1" * 20
    DB_USER, DB_PASSWORD = "msuedu_user", "Str0ngPassw0rd!"
    SESSION_COOKIE_SECURE = True
    CSP_ENABLED = True
    SHOW_SYSTEM_STATUS = False
    AI_PROVIDER, AI_API_KEY, AI_MODEL, AI_BASE_URL = "openai", "k", "m", "https://api.example.test/v1"
    TURN_URLS, TURN_USERNAME, TURN_CREDENTIAL = "turn:t.example:3478", "u", "c"
    REMINDERS_ENABLED = False


def project_files(*suffixes):
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix in suffixes and not (set(path.relative_to(ROOT).parts) & SKIP_DIRS):
            yield path


def test_booking_update_email_template_renders_escaped_content():
    app = create_app(P20Config)
    with app.app_context():
        rendered = app.jinja_env.get_template("emails/booking_update.html").render(
            title="Request accepted",
            recipient_name="<Student>",
            body="Your tutoring request was accepted.",
            link="https://example.test/requests/1",
        )

    assert "Request accepted" in rendered
    assert "&lt;Student&gt;" in rendered
    assert "Your tutoring request was accepted." in rendered
    assert 'href="https://example.test/requests/1"' in rendered
    assert "View booking" in rendered


def test_booking_update_email_uses_smtp_and_includes_html(monkeypatch):
    class FakeSMTP:
        message = None

        def __init__(self, host, port, timeout):
            self.host, self.port, self.timeout = host, port, timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def ehlo(self):
            pass

        def starttls(self, context):
            self.tls_context = context

        def login(self, username, password):
            self.credentials = (username, password)

        def send_message(self, message):
            FakeSMTP.message = message

    monkeypatch.setattr(mail_service.smtplib, "SMTP", FakeSMTP)
    app = create_app(P20Config)
    app.config.update(TESTING=False, SMTP_HOST="smtp.example.test", SMTP_PORT=587,
                      SMTP_USER="mailer@example.test", SMTP_PASS="test-secret",
                      MAIL_BASE_URL="https://msuedu.example")
    with app.app_context():
        sent = mail_service.send_booking_update("student@example.test", "Student",
                                               "Request accepted", "Your session is confirmed.",
                                               "/student/requests")

    assert sent is True
    assert FakeSMTP.message["To"] == "student@example.test"
    assert FakeSMTP.message["Subject"] == "Request accepted"
    html = FakeSMTP.message.get_body(preferencelist=("html",)).get_content()
    assert "https://msuedu.example/student/requests" in html
    assert "Your session is confirmed." in html


# ======================= splitting SQL =======================
def test_split_sql_respects_quotes_and_comments():
    text = ("USE x;  -- a comment; with a semicolon\n"
            "INSERT INTO t VALUES ('a;b', 'it''s', \"q;\");\n\n"
            "ALTER TABLE t ADD c INT   -- trailing\n")
    assert dc.split_sql(text) == ["USE x", "INSERT INTO t VALUES ('a;b', 'it''s', \"q;\")", "ALTER TABLE t ADD c INT"]
    assert dc.split_sql(r"INSERT INTO t VALUES ('a\';b');") == [r"INSERT INTO t VALUES ('a\';b')"]
    assert dc.split_sql("INSERT INTO t VALUES ('has -- dashes; inside');") == ["INSERT INTO t VALUES ('has -- dashes; inside')"]
    assert dc.split_sql("") == [] and dc.split_sql("  ;; \n -- only a comment") == []


def test_schema_files_are_ordered_numerically():
    names = ["schema_phase10.sql", "schema_phase2.sql", "setup_phase1.sql", "schema_phase9.sql",
             "notes.txt", "schema_phaseX.sql", "schema_phase3.sql"]
    assert dc.order_schema_files(names) == ["schema_phase2.sql", "schema_phase3.sql", "schema_phase9.sql",
                                            "schema_phase10.sql"]
    assert dc.order_schema_files(iter([])) == []


SCHEMA_FILES = sorted((ROOT / "database").glob("schema_phase*.sql"))


def all_statements():
    out = []
    for path in dc.order_schema_files(p.name for p in SCHEMA_FILES):
        out += dc.split_sql((ROOT / "database" / path).read_text(encoding="utf-8"))
    return out


def test_every_schema_file_splits_into_known_statements():
    assert len(SCHEMA_FILES) >= 15
    for path in SCHEMA_FILES:
        statements = dc.split_sql(path.read_text(encoding="utf-8"))
        assert statements, f"{path.name} has no statements (is it empty?)"
        for statement in statements:
            assert statement.split()[0].upper() in {"USE", "CREATE", "ALTER", "INSERT"}, \
                f"{path.name}: unexpected statement starting {statement[:40]!r}"


def test_the_schema_files_create_exactly_the_expected_tables():
    created = set()
    for statement in all_statements():
        match = re.match(r"CREATE TABLE IF NOT EXISTS (\w+)", statement)
        if match:
            created.add(match.group(1))
    assert created == set(dc.EXPECTED_TABLES) and len(dc.EXPECTED_TABLES) == 30
    statements = all_statements()
    for table, column in dc.EXPECTED_COLUMNS:
        assert any(table in s and column in s for s in statements), f"{table}.{column} is not in any schema file"


def test_missing_schema_reports_gaps():
    tables = set(dc.EXPECTED_TABLES)
    columns = set(dc.EXPECTED_COLUMNS)
    assert dc.missing_schema(tables, columns) == ([], [])
    tables.discard("session_files")
    columns.discard(("users", "session_version"))
    assert dc.missing_schema(tables, columns) == (["session_files"], ["users.session_version"])


# ======================= applying statements =======================
class FakeCursor:
    def __init__(self, log, errors=None):
        self.log, self.errors = log, errors or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.log.append(sql)
        for fragment, error in self.errors.items():
            if fragment in sql:
                raise error


def test_apply_skips_use_and_already_applied_changes_but_stops_on_real_errors():
    log = []
    errors = {"ADD one": pymysql.err.OperationalError(1060, "Duplicate column name 'one'"),
              "ADD two": pymysql.err.OperationalError(1826, "Duplicate foreign key constraint name"),
              "BROKEN": pymysql.err.ProgrammingError(1064, "syntax error")}
    cur = FakeCursor(log, errors)
    assert ops._apply(cur, ["USE msuedu_ai", "CREATE TABLE a (id INT)", "ALTER t ADD one", "ALTER t ADD two"]) == (1, 2)
    assert "USE msuedu_ai" not in log
    with pytest.raises(pymysql.err.ProgrammingError):
        ops._apply(cur, ["BROKEN statement"])


class FakeConn:
    def __init__(self):
        self.log, self.commits, self.closed = [], 0, False

    def cursor(self):
        return FakeCursor(self.log)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def cli(monkeypatch, tables, columns, command):
    app = create_app(P20Config)
    ops.register_ops(app)
    conn = FakeConn()
    monkeypatch.setattr(ops, "get_connection", lambda: conn)
    monkeypatch.setattr(ops, "query_all", lambda sql, params=None: (
        [{"t": t} for t in tables] if "information_schema.tables" in sql else [{"t": t, "c": c} for t, c in columns]))
    return conn, app.test_cli_runner().invoke(args=[command])


def test_init_db_applies_every_file_in_order_then_verifies(monkeypatch):
    conn, result = cli(monkeypatch, dc.EXPECTED_TABLES, dc.EXPECTED_COLUMNS, "init-db")
    assert result.exit_code == 0 and "Schema is complete" in result.output
    assert conn.commits == len(SCHEMA_FILES) and conn.closed
    assert not any(s.upper().startswith("USE ") for s in conn.log)
    order = [i for i, s in enumerate(conn.log) if s.startswith("CREATE TABLE IF NOT EXISTS")]
    assert "users" in conn.log[order[0]] and any("tutor_subjects" in conn.log[i] for i in order)
    assert result.output.index("schema_phase2.sql") < result.output.index("schema_phase10.sql") \
        if "schema_phase10.sql" in result.output else True


def test_init_db_and_verify_report_missing_pieces(monkeypatch):
    _conn, result = cli(monkeypatch, [t for t in dc.EXPECTED_TABLES if t != "topics"], dc.EXPECTED_COLUMNS, "init-db")
    assert result.exit_code == 1 and "Missing tables: topics" in result.output
    _conn, result = cli(monkeypatch, dc.EXPECTED_TABLES, [c for c in dc.EXPECTED_COLUMNS if c[1] != "topic_id"],
                        "verify-schema")
    assert result.exit_code == 1 and "quizzes.topic_id" in result.output
    _conn, ok = cli(monkeypatch, dc.EXPECTED_TABLES, dc.EXPECTED_COLUMNS, "verify-schema")
    assert ok.exit_code == 0


# ======================= the settings review =======================
GOOD = {"SECRET_KEY": "a1" * 20, "DB_USER": "msuedu_user", "DB_PASSWORD": "Str0ngPassw0rd!",
        "SESSION_COOKIE_SECURE": True, "CSP_ENABLED": True, "SHOW_SYSTEM_STATUS": False,
        "AI_PROVIDER": "openai", "AI_API_KEY": "k", "AI_MODEL": "m", "AI_BASE_URL": "https://api.example.test/v1",
        "TURN_URLS": "turn:t.example:3478", "TURN_USERNAME": "u", "TURN_CREDENTIAL": "c", "REMINDERS_ENABLED": False}


def levels(cfg, **kw):
    return [level for level, _text in dc.check_settings(cfg, **kw)]


def test_a_good_production_setup_has_no_errors_or_warnings():
    results = dc.check_settings(GOOD, debug=False, trust_proxy=True)
    assert not any(level in ("error", "warn") for level, _ in results) and not dc.has_errors(results)


@pytest.mark.parametrize("change,kw,expected", [
    ({"SECRET_KEY": "short"}, {}, "error"), ({"SECRET_KEY": "replace-with-a-long-random-string-xxxxxxxx"}, {}, "error"),
    ({}, {"debug": True}, "error"), ({"SESSION_COOKIE_SECURE": False}, {}, "error"),
    ({"CSP_ENABLED": False}, {}, "error"), ({"DB_USER": "root"}, {}, "error"), ({"DB_USER": ""}, {}, "error"),
    ({"DB_PASSWORD": ""}, {}, "error"), ({"AI_API_KEY": ""}, {}, "error"), ({"AI_PROVIDER": "banana"}, {}, "error"),
    ({"SHOW_SYSTEM_STATUS": True}, {}, "warn"), ({"AI_BASE_URL": "http://insecure.example"}, {}, "warn"),
    ({"AI_PROVIDER": "ollama"}, {}, "warn"), ({"TURN_URLS": ""}, {}, "warn"), ({}, {"trust_proxy": False}, "warn")])
def test_each_unsafe_setting_is_reported(change, kw, expected):
    kw = {"trust_proxy": True, **kw}
    assert expected in levels({**GOOD, **change}, **kw)
    if expected == "error":
        assert dc.has_errors(dc.check_settings({**GOOD, **change}, **kw))


def test_check_config_command_exit_codes(monkeypatch):
    monkeypatch.setenv("APP_DEBUG", "false")
    monkeypatch.setenv("TRUST_PROXY", "true")
    bad = create_app(P20Config)
    ops.register_ops(bad)
    result = bad.test_cli_runner().invoke(args=["check-config"])
    assert result.exit_code == 1 and "[ERROR]" in result.output and "error(s)" in result.output
    good = create_app(GoodConfig)
    ops.register_ops(good)
    ok = good.test_cli_runner().invoke(args=["check-config"])
    assert ok.exit_code == 0 and "[ERROR]" not in ok.output and "0 error(s)" in ok.output
    monkeypatch.setenv("APP_DEBUG", "true")
    assert good.test_cli_runner().invoke(args=["check-config"]).exit_code == 1


def test_socket_origins_parsing():
    assert dc.parse_origins("") is None and dc.parse_origins(None) is None
    assert dc.parse_origins("https://a.example, http://localhost:5000/ ,https://b.example") == [
        "https://a.example", "http://localhost:5000", "https://b.example"]
    assert dc.parse_origins("*") is None and dc.parse_origins("javascript:alert(1), ftp://x.example") is None


# ======================= security review =======================
ACTION_VALUES = {"bookings.act": "accept", "admin.user_action": "activate", "admin.feedback_action": "hide"}


def test_every_post_route_refuses_a_missing_csrf_token():
    app = create_app(CsrfOnConfig)
    adapter = app.url_map.bind("localhost")
    client = app.test_client()
    checked = 0
    for rule in app.url_map.iter_rules():
        if "POST" not in rule.methods or rule.rule.startswith("/socket.io"):
            continue
        values = {arg: (ACTION_VALUES[rule.endpoint] if arg == "action" else 1) for arg in rule.arguments}
        url = adapter.build(rule.endpoint, values)
        response = client.post(url)
        assert response.status_code == 400, f"POST {url} ({rule.endpoint}) works without a CSRF token"
        checked += 1
    assert checked > 40


def test_a_state_changing_page_is_never_a_plain_link():
    """Logging out, and every action, must be POST: opening them as a link must not do anything."""
    client = create_app(P20Config).test_client()
    assert client.get("/logout").status_code == 405


def test_no_secrets_in_the_project():
    patterns = [re.compile(r"sk-[A-Za-z0-9]{20,}"), re.compile(r"AKIA[0-9A-Z]{16}"),
                re.compile(r"BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY")]
    files = [p for p in project_files(".py", ".html", ".js", ".css", ".sql", ".md", ".ps1", ".example")
             if not p.name.endswith(".min.js")]
    files += [p for p in ROOT.glob(".env*") if p.is_file() and p.name.endswith(".example")]
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in patterns:
            assert not pattern.search(text), f"{path.name} contains something that looks like a secret"


def test_no_hardcoded_credentials_in_app_code():
    pattern = re.compile(r"(?i)\b(password|secret_key|api_key)\s*=\s*[\"'][^\"']{6,}[\"']")
    for path in (ROOT / "app").rglob("*.py"):
        assert not pattern.search(path.read_text(encoding="utf-8")), f"{path.name} has a hard-coded credential"


def test_gitignore_protects_secrets_data_and_backups():
    lines = {line.strip() for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
    assert {".env", "venv/", "uploads/", "backups/"} <= lines and ".env.example" not in lines


def test_example_environment_files_contain_only_placeholders():
    example = (ROOT / ".env.production.example").read_text(encoding="utf-8")
    values = dict(line.split("=", 1) for line in example.splitlines() if "=" in line and not line.startswith("#"))
    assert values["APP_DEBUG"] == "false" and values["SESSION_COOKIE_SECURE"] == "true"
    assert values["TRUST_PROXY"] == "true" and values["SHOW_SYSTEM_STATUS"] == "false" and values["CSP_ENABLED"] == "true"
    assert values["SECRET_KEY"].startswith("replace") and values["AI_API_KEY"] == "" and values["TURN_CREDENTIAL"] == ""
    assert all(not v.startswith("sk-") for v in values.values())


def test_templates_never_turn_off_escaping():
    for path in (ROOT / "app" / "templates").rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        assert "|safe" not in text.replace(" ", "") and "{% autoescape" not in text, f"{path.name} disables escaping"
    for path in (ROOT / "app").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "Markup(" not in source and "render_template_string" not in source, f"{path.name} bypasses escaping"


def test_sql_built_with_f_strings_never_embeds_request_data():
    sql = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE)\b")
    request_data = re.compile(r"\b(request|form|args)\.")
    for path in (ROOT / "app").rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if re.search(r"""\bf["']""", line) and sql.search(line):
                assert not request_data.search(line), f"{path.name}:{number} puts request data inside SQL"


def test_cookie_flags_and_hsts_in_a_production_like_setup():
    app = create_app(GoodConfig)
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True and app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    headers = app.test_client().get("/login").headers
    assert "max-age=31536000" in headers["Strict-Transport-Security"]
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"] and headers["X-Frame-Options"] == "DENY"


# ======================= deployment pieces =======================
def test_healthz_is_public_and_touches_nothing(monkeypatch):
    def boom():
        raise AssertionError("the health check must not touch the database")
    monkeypatch.setattr(main_routes, "check_database", boom)
    app = create_app(P20Config)
    app.config["SHOW_SYSTEM_STATUS"] = False
    response = app.test_client().get("/healthz")
    assert response.status_code == 200 and response.get_json() == {"status": "ok"}
    assert app.test_client().get("/health").status_code == 404           # the detailed one stays off


def test_deployment_files_exist_and_say_the_important_things():
    for name in ("wsgi.py", "backup-db.ps1", ".env.production.example", "README.md", "docs/ARCHITECTURE.md",
                 "docs/SECURITY.md", "docs/DEPLOYMENT.md", "docs/DEFENSE_GUIDE.md"):
        assert (ROOT / name).is_file() and (ROOT / name).stat().st_size > 200, f"{name} is missing or empty"
    wsgi = (ROOT / "wsgi.py").read_text(encoding="utf-8")
    assert "from run import app" in wsgi and "START_SCHEDULER" in wsgi and "-w 1" in wsgi
    deploy = (ROOT / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8")
    for needle in ("-w 1", "TURN", "check-config", "init-db", "client_max_body_size", "Upgrade"):
        assert needle in deploy
    assert "init-db" in (ROOT / "README.md").read_text(encoding="utf-8")
    defense = (ROOT / "docs" / "DEFENSE_GUIDE.md").read_text(encoding="utf-8")
    assert "Agentic" in defense and "seed-demo" in defense and "12-step" in defense
    assert "pip-audit" in (ROOT / "docs" / "SECURITY.md").read_text(encoding="utf-8")


def test_the_backup_script_keeps_the_password_off_the_command_line():
    script = (ROOT / "backup-db.ps1").read_text(encoding="utf-8")
    assert "--defaults-extra-file" in script and "Remove-Item $cnf" in script and "-p$" not in script
    assert "--password" not in script


# ======================= demonstration data =======================
def test_the_python_tutor_and_learning_data_are_part_of_the_demo():
    subjects = [name for name, _topics in demo_data.TUTOR_SETUP["tutor1"]["subjects"]]
    assert "Python Programming" in subjects


def test_learning_data_is_skipped_with_a_clear_note_when_lessons_are_missing(monkeypatch):
    monkeypatch.setattr(demo_data, "query_one", lambda sql, params=None: None)
    monkeypatch.setattr(demo_data, "execute", lambda *a, **k: pytest.fail("nothing may be written"))
    note = demo_data._seed_learning({"student1": 1})
    assert "init-db" in note and "not found" in note


def test_the_sample_quiz_history_produces_a_review_recommendation():
    """100%, 75%, 25% on a topic whose lesson is not finished must lead to 'review the lesson'."""
    from app.services import learning_agent, profile_service
    rows = [{"topic_id": 1, "topic_name": "Functions", "subject_id": 4, "subject_name": "Python Programming",
             "score": s, "total": 4} for s in (4, 3, 1)]
    topic = profile_service.summarize_topics(rows)[0]
    assert topic["status"] == "weak" and topic["latest"] == 25
    lessons = {"total": 1, "done": 0, "next": {"id": 9, "title": "Functions", "topic": "Functions"}}
    assert learning_agent.decide_topic(topic, lessons)["kind"] == "review_lesson"
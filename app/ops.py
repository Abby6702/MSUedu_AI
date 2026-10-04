"""Command-line tools for setting up and checking a deployment:
    flask --app run init-db         create or update every table (safe to run again)
    flask --app run verify-schema   list missing tables or columns
    flask --app run check-config    review settings before going live"""
import os
from pathlib import Path

import click
import pymysql

from app import deploy_checks
from app.db import get_connection, query_all


def _apply(cursor, statements):
    """Run statements, skipping ones that are already in place. Returns (applied, skipped)."""
    applied = skipped = 0
    for statement in statements:
        if statement[:4].upper() == "USE ":
            continue                                          # the connection already selects the database
        try:
            cursor.execute(statement)
        except pymysql.err.MySQLError as error:
            if error.args and error.args[0] in deploy_checks.IGNORABLE_ERRORS:
                skipped += 1
                continue
            raise
        applied += 1
    return applied, skipped


def _schema_gaps():
    tables = {r["t"] for r in query_all(
        "SELECT table_name AS t FROM information_schema.tables WHERE table_schema = DATABASE()")}
    columns = {(r["t"], r["c"]) for r in query_all(
        "SELECT table_name AS t, column_name AS c FROM information_schema.columns "
        "WHERE table_schema = DATABASE()")}
    return deploy_checks.missing_schema(tables, columns)


def _report_gaps():
    """Print the result. Returns True if the schema is complete."""
    tables, columns = _schema_gaps()
    if not tables and not columns:
        click.echo(f"Schema is complete: all {len(deploy_checks.EXPECTED_TABLES)} tables and the added columns exist.")
        return True
    if tables:
        click.echo("Missing tables: " + ", ".join(tables))
    if columns:
        click.echo("Missing columns: " + ", ".join(columns))
    return False


def register_ops(app):
    @app.cli.command("init-db")
    def init_db():
        """Create or update every table. Safe to run again."""
        folder = Path(app.root_path).parent / "database"
        names = deploy_checks.order_schema_files(p.name for p in folder.glob("schema_phase*.sql"))
        if not names:
            raise click.ClickException("No schema_phase*.sql files were found in the database folder.")
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                for name in names:
                    statements = deploy_checks.split_sql((folder / name).read_text(encoding="utf-8"))
                    try:
                        applied, skipped = _apply(cur, statements)
                    except pymysql.err.MySQLError as error:
                        raise click.ClickException(f"{name} stopped: {error}") from error
                    conn.commit()
                    click.echo(f"{name}: {applied} applied, {skipped} already in place")
        finally:
            conn.close()
        if not _report_gaps():
            raise SystemExit(1)

    @app.cli.command("verify-schema")
    def verify_schema():
        """Check that every expected table and column exists."""
        if not _report_gaps():
            raise SystemExit(1)

    @app.cli.command("check-config")
    def check_config():
        """Review the settings before going live. Exits with 1 if something unsafe is set."""
        debug = os.getenv("APP_DEBUG", "true").lower() == "true"
        proxy = os.getenv("TRUST_PROXY", "false").lower() == "true"
        results = deploy_checks.check_settings(app.config, debug=debug, trust_proxy=proxy)
        labels = {"ok": "[OK]   ", "info": "[INFO] ", "warn": "[WARN] ", "error": "[ERROR]"}
        for level, text in results:
            click.echo(f"{labels[level]} {text}")
        errors = sum(1 for level, _t in results if level == "error")
        warnings = sum(1 for level, _t in results if level == "warn")
        click.echo(f"\n{errors} error(s), {warnings} warning(s).")
        if errors:
            raise SystemExit(1)
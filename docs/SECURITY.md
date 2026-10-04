# Security review

## Controls and where to find them
| Threat | Control | Evidence |
|---|---|---|
| SQL injection | Every query uses `%s` parameters. Dynamic SQL is built only from fixed fragments. | Tests for search, filters and the SQL-string heuristic. |
| Cross-site scripting | Jinja escaping, `textContent` in scripts, strict Content-Security-Policy, no `\|safe` | Template and script checks in the tests. |
| CSRF | Flask-WTF token on every form and JSON POST, `SameSite=Lax` cookies | `test_phase20`: every POST route is refused without a token. |
| Broken access control | Role decorators on every route, ownership checks inside SQL, 404 for other people's records | Phase 10 route matrix plus per-feature tests. |
| Password attacks | Hashed passwords, lockout per account and per IP, generic errors, admin-assisted reset with forced change | Phase 9 tests. |
| Session misuse | Signed HttpOnly cookies, fresh session at login, version check ends old sessions after a password change or deactivation | Phase 9 tests. |
| Unsafe uploads | Extension allow-list, real content checks, ZIP and macro checks, random names, outside `static/`, always downloaded as attachments | Phase 15 and 17 tests. |
| Real-time abuse | Socket authentication, same-origin (or allow-listed) connections, rebuilt and size-capped messages, rate limits | Phase 16 and 17 tests. |
| AI misuse | Server-side calls, rate limits, validated output, no student name in tutor prompts, prompt-injection treated as data | Phase 5 to 18 tests. |
| Secret leaks | `.env` only, ignored by Git, placeholders in examples | Secrets scan test. |
| Error leaks | Friendly error pages, technical detail only in server logs | Phase 9 tests. |

## Known limits (not hidden)
- No multi-factor login and no email recovery. Resets are administrator-assisted.
- Sessions are signed, not encrypted, and cannot be revoked one by one.
- Chats, summaries and files are stored unencrypted in the database and on disk. Anyone with server or database access can read them.
- Uploads are not virus-scanned.
- Whiteboard and rooms are in memory, so a restart ends live sessions.
- Lockout can be abused to annoy a user for 15 minutes. That is the usual trade-off.
- Behind a proxy, visitor IPs are trusted only when `TRUST_PROXY` matches exactly one proxy in front.
- There is no self-service account deletion or data export yet.
- Dependencies were not audited by me: run `pip install pip-audit` then `pip-audit` before launch and update what it flags.

## Before launch
1. `python -m pytest -v` passes. 2. `flask --app run check-config` shows no errors. 3. HTTPS works and
`SESSION_COOKIE_SECURE=true`. 4. Database user is not `root`. 5. `APP_DEBUG=false`. 6. Strong admin password,
registration closed unless wanted. 7. Backups run and a restore was tested. 8. `pip-audit` read and acted on.
9. Real data only with permission and a privacy review. 10. Someone knows how to rotate `SECRET_KEY`
(everyone is logged out) and how to deactivate accounts.

## If something goes wrong
Deactivate affected accounts (Admin > Users), rotate `SECRET_KEY`, read the Audit log, restore from backup
if data was damaged, and tell the people affected.
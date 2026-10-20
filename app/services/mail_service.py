"""Outbound email delivery for booking updates."""
import smtplib
import ssl
from email.message import EmailMessage
from flask import current_app, render_template


def _absolute_link(path):
    base_url = current_app.config.get("MAIL_BASE_URL", "").rstrip("/")
    if base_url and isinstance(path, str) and path.startswith("/") and not path.startswith("//"):
        return base_url + path
    return ""


def send_booking_update(recipient_email, recipient_name, title, body, link):
    """Send one booking update when SMTP is configured; return False when disabled."""
    config = current_app.config
    host, port = config.get("SMTP_HOST"), config.get("SMTP_PORT")
    sender = config.get("SMTP_FROM") or config.get("SMTP_USER")
    username, password = config.get("SMTP_USER"), config.get("SMTP_PASS")
    if (current_app.testing or not host or not port or not sender or not recipient_email):
        return False

    action_url = _absolute_link(link)
    message = EmailMessage()
    message["Subject"] = title
    message["From"] = sender
    message["To"] = recipient_email
    text = f"Hello {recipient_name},\n\n{body}"
    if action_url:
        text += f"\n\nView booking: {action_url}"
    message.set_content(text)
    message.add_alternative(render_template(
        "emails/booking_update.html", title=title, recipient_name=recipient_name,
        body=body, link=action_url), subtype="html")

    if int(port) == 465:
        with smtplib.SMTP_SSL(host, int(port), timeout=10,
                              context=ssl.create_default_context()) as server:
            if username and password:
                server.login(username, password)
            server.send_message(message)
    else:
        with smtplib.SMTP(host, int(port), timeout=10) as server:
            if config.get("SMTP_STARTTLS", True):
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            if username and password:
                server.login(username, password)
            server.send_message(message)
    return True
"""Runs session reminders in the background with APScheduler.
It works locally with no extra services."""
from app.services import notification_service


def run_reminder_job(app):
    with app.app_context():
        try:
            hours = notification_service.parse_hours(app.config["REMINDER_HOURS"])
            sent = notification_service.send_due_reminders(hours)
            if sent:
                app.logger.info("Reminders sent: %s", sent)
        except Exception:
            app.logger.exception("The reminder job failed")   # never stops the scheduler


def start_scheduler(app):
    """Start the background job. Returns the scheduler, or None if reminders are off."""
    if not app.config.get("REMINDERS_ENABLED"):
        return None
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(run_reminder_job, "interval", args=[app],
                      minutes=max(1, app.config["REMINDER_CHECK_MINUTES"]),
                      id="reminders", max_instances=1, coalesce=True)
    scheduler.start()
    return scheduler
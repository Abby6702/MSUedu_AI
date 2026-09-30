"""Start the app with:  python run.py"""
import os

from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app
from app.demo_data import register_commands
from app.scheduler import start_scheduler

app = create_app()
register_commands(app)      # adds:  flask --app run seed-demo / remove-demo

# Only turn this on when a tunnel or proxy is in front of the app. It makes Flask trust the
# proxy's "real IP / https / host" headers, which anyone could fake if the app were exposed directly.
if os.getenv("TRUST_PROXY", "false").lower() == "true":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

if __name__ == "__main__":
    DEBUG = os.getenv("APP_DEBUG", "true").lower() == "true"
    HOST = os.getenv("APP_HOST", "127.0.0.1")
    if not DEBUG or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_scheduler(app)
    app.run(host=HOST, debug=DEBUG)
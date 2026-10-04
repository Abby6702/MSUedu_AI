"""Start the app with:  python run.py   (development).  In production use wsgi.py with gunicorn."""
import os

from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app
from app.demo_data import register_commands
from app.extensions import socketio
from app.ops import register_ops
from app.scheduler import start_scheduler

app = create_app()
register_commands(app)      # flask --app run seed-demo / remove-demo
register_ops(app)           # flask --app run init-db / verify-schema / check-config

# Only turn this on when exactly ONE tunnel or proxy is in front of the app. It makes Flask trust that
# proxy's "real IP / https / host" headers, which anyone could fake if the app were exposed directly.
if os.getenv("TRUST_PROXY", "false").lower() == "true":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

if __name__ == "__main__":
    DEBUG = os.getenv("APP_DEBUG", "true").lower() == "true"
    HOST = os.getenv("APP_HOST", "127.0.0.1")
    if not DEBUG or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_scheduler(app)
    # Development server only. allow_unsafe_werkzeug lets it run with debug off for demos.
    socketio.run(app, host=HOST, debug=DEBUG, allow_unsafe_werkzeug=True)
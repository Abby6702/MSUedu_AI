"""Reads settings from environment variables (loaded from the .env file)."""
import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()  # loads values from .env into the environment


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")

    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_NAME = os.getenv("DB_NAME", "msuedu_ai")

    # Development helper: show DB status on the homepage. Turn off later.
    SHOW_SYSTEM_STATUS = os.getenv("SHOW_SYSTEM_STATUS", "true").lower() == "true"

    # Store times in UTC, display them in Philippine time
    TIMEZONE = "Asia/Manila"

    # Local AI (Ollama). These stay on the server and are never sent to the browser.
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "")            # must match `ollama list`
    OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))  # seconds to wait for an answer
    OLLAMA_MAX_TOKENS = int(os.getenv("OLLAMA_MAX_TOKENS", "800"))  # longest answer

    
    # Which AI service to use: "ollama" (local, default) or "openai" (any OpenAI-compatible service).
    # The key is read from .env only and is never sent to the browser.
    AI_PROVIDER = os.getenv("AI_PROVIDER", "ollama").strip().lower()
    AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
    AI_API_KEY = os.getenv("AI_API_KEY", "")
    AI_MODEL = os.getenv("AI_MODEL", "")

    # Session reminders
    REMINDERS_ENABLED = os.getenv("REMINDERS_ENABLED", "true").lower() == "true"
    REMINDER_HOURS = os.getenv("REMINDER_HOURS", "24,1")      # remind this many hours before
    REMINDER_CHECK_MINUTES = int(os.getenv("REMINDER_CHECK_MINUTES", "5"))

    # Sessions: logged out automatically after 2 hours
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
    WTF_CSRF_TIME_LIMIT = 7200  # forms stay valid for 2 hours

    # Safer session cookies
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Set SESSION_COOKIE_SECURE=true in .env ONLY when the site is served over HTTPS.
    # (On plain http://localhost the browser would refuse to keep the login cookie.)
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"

    # Reject request bodies larger than 1 MB
    MAX_CONTENT_LENGTH = 1024 * 1024

    # Browser security policy (set CSP_ENABLED=false in .env only to debug a broken page)
    CSP_ENABLED = os.getenv("CSP_ENABLED", "true").lower() == "true"

    
       # Optional allow-list of sites that may open a live-session socket, for example
       # "https://your-domain.example". Empty means same-origin only. A wildcard is never accepted.
    SOCKETIO_ORIGINS = os.getenv("SOCKETIO_ORIGINS", "")
    
    # Where uploaded files are stored. Keep this OUTSIDE app/static so files are never public.
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "uploads")

    
    # WebRTC connection helpers. STUN is free and enough for many networks (this default is a
    # public Google server, which sees users' network addresses). TURN relays video when a direct
    # connection is impossible: get URLs and credentials from a TURN provider or your own server.
    # These values are sent to the browsers in the room, so use a dedicated account for them.
    STUN_URLS = os.getenv("STUN_URLS", "stun:stun.l.google.com:19302")
    TURN_URLS = os.getenv("TURN_URLS", "")
    TURN_USERNAME = os.getenv("TURN_USERNAME", "")
    TURN_CREDENTIAL = os.getenv("TURN_CREDENTIAL", "")
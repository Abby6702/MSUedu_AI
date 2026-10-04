"""Pure rules for live sessions (no database, no network), so they are easy to test."""
from datetime import timedelta
from time import monotonic

OPENS_BEFORE = timedelta(minutes=15)
CLOSES_AFTER = timedelta(minutes=60)
SIGNAL_TYPES = ("offer", "answer", "candidate")
MAX_SDP = 20000
MAX_CHAT = 1000
ICE_SCHEMES = ("stun:", "stuns:", "turn:", "turns:")


def join_state(status, start, end, now):
    """Returns (state, message). state: open, early, ended or unavailable (all UTC)."""
    if status != "accepted":
        return "unavailable", "This session is not confirmed, so there is no live room for it."
    if now < start - OPENS_BEFORE:
        return "early", "The room opens 15 minutes before the session starts. Come back then."
    if now > end + CLOSES_AFTER:
        return "ended", "This session's room has closed."
    return "open", ""


def room_deadline(end):
    return end + CLOSES_AFTER


def _urls(text):
    return [u.strip() for u in (text or "").split(",") if u.strip().lower().startswith(ICE_SCHEMES)]


def build_ice_servers(cfg):
    """The connection helpers sent to the browser. TURN is included only if fully configured."""
    servers = []
    stun = _urls(cfg.get("STUN_URLS"))
    if stun:
        servers.append({"urls": stun})
    turn = _urls(cfg.get("TURN_URLS"))
    if turn and cfg.get("TURN_USERNAME") and cfg.get("TURN_CREDENTIAL"):
        servers.append({"urls": turn, "username": cfg["TURN_USERNAME"],
                        "credential": cfg["TURN_CREDENTIAL"]})
    return servers


def validate_signal(payload):
    """A WebRTC setup message from a browser -> a REBUILT message with only known fields,
    or None. Nothing the browser adds beyond these fields is ever relayed."""
    if not isinstance(payload, dict):
        return None
    kind, data = payload.get("type"), payload.get("data")
    if kind not in SIGNAL_TYPES or not isinstance(data, dict):
        return None
    if kind in ("offer", "answer"):
        sdp = data.get("sdp")
        if data.get("type") != kind or not isinstance(sdp, str) or not 10 <= len(sdp) <= MAX_SDP:
            return None
        return {"type": kind, "data": {"type": kind, "sdp": sdp}}
    candidate = data.get("candidate")
    if not isinstance(candidate, str) or len(candidate) > 1000:
        return None
    clean = {"candidate": candidate}
    mid, index, fragment = data.get("sdpMid"), data.get("sdpMLineIndex"), data.get("usernameFragment")
    if isinstance(mid, str) and len(mid) <= 64:
        clean["sdpMid"] = mid
    if isinstance(index, int) and not isinstance(index, bool) and 0 <= index <= 64:
        clean["sdpMLineIndex"] = index
    if isinstance(fragment, str) and len(fragment) <= 256:
        clean["usernameFragment"] = fragment
    return {"type": "candidate", "data": clean}


def clean_chat(text):
    """Chat text without control characters, 1 to 1000 characters, or None."""
    if not isinstance(text, str):
        return None
    text = "".join(ch for ch in text if ch == "\n" or (ch >= " " and ch != "\x7f")).strip()
    return text if 1 <= len(text) <= MAX_CHAT else None


def allow(bucket, limit, per_seconds, now=None):
    """Simple rate limit: at most `limit` events per `per_seconds`. bucket is a deque."""
    now = monotonic() if now is None else now
    while bucket and now - bucket[0] > per_seconds:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True
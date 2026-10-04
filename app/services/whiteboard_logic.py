"""Pure rules for the shared whiteboard (no database, no network, no Flask), so they are easy
to test. Coordinates are fractions of the board (0 to 1), so any screen size works."""
import math
import re
import unicodedata

ID_RE = re.compile(r"^[st][A-Za-z0-9_-]{1,31}$")    # first letter: s = student, t = tutor
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_CHUNK_POINTS = 100
MAX_STROKE_POINTS = 3000
MAX_TOTAL_POINTS = 30000
MAX_OPS = 1500
MAX_REDO = 50
MAX_TEXT = 200


def _point(p):
    if not isinstance(p, (list, tuple)) or len(p) != 2:
        return None
    out = []
    for v in p:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1:
            return None
        out.append(round(float(v), 4))
    return out


def _int_between(value, low, high):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def clean_text(text):
    """One line of text without control or invisible formatting characters, or None."""
    if not isinstance(text, str):
        return None
    text = "".join(" " if ch in "\r\n\t" else ch for ch in text)
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")
    text = " ".join(text.split())
    return text if 1 <= len(text) <= MAX_TEXT else None


def clean_draw(payload):
    """A drawing message from a browser -> a REBUILT message with only known fields, or None."""
    if not isinstance(payload, dict):
        return None
    op_id = payload.get("id")
    if not isinstance(op_id, str) or not ID_RE.match(op_id):
        return None
    kind = payload.get("kind")

    if kind == "stroke":
        tool = payload.get("tool")
        if tool not in ("pen", "eraser"):
            return None
        color = "#ffffff"                                     # the eraser always paints white
        if tool == "pen":
            raw = payload.get("color")
            if not isinstance(raw, str) or not COLOR_RE.match(raw):
                return None
            color = raw.lower()
        if not _int_between(payload.get("size"), 1, 40):
            return None
        raw_points = payload.get("points")
        if not isinstance(raw_points, list) or not raw_points or len(raw_points) > MAX_CHUNK_POINTS:
            return None
        points = [_point(p) for p in raw_points]
        if any(p is None for p in points):
            return None
        return {"id": op_id, "kind": "stroke", "tool": tool, "color": color,
                "size": payload["size"], "points": points}

    if kind == "text":
        raw = payload.get("color")
        if not isinstance(raw, str) or not COLOR_RE.match(raw):
            return None
        point = _point([payload.get("x"), payload.get("y")])
        text = clean_text(payload.get("text"))
        if point is None or text is None or not _int_between(payload.get("size"), 12, 64):
            return None
        return {"id": op_id, "kind": "text", "x": point[0], "y": point[1], "text": text,
                "color": raw.lower(), "size": payload["size"]}
    return None


def _public(op):
    copy = dict(op)
    if copy["kind"] == "stroke":
        copy["points"] = [p[:] for p in op["points"]]
    return copy


class Board:
    """The drawing of one session. Every item's id starts with its owner's letter, so each person
    can only extend, undo or redo their own work."""

    def __init__(self):
        self.ops, self.by_id, self.points = [], {}, 0
        self.redo_stacks = {"s": [], "t": []}

    @staticmethod
    def _letter(role):
        return "t" if role == "tutor" else "s"

    def _add(self, letter, op):
        self.ops.append(op)
        self.by_id[op["id"]] = op
        if op["kind"] == "stroke":
            self.points += len(op["points"])
        self.redo_stacks[letter].clear()                      # new work ends the redo history
        return _public(op)

    def draw(self, role, op):
        """Add a new item or extend a stroke. Returns what to relay to the other person, or None."""
        letter = self._letter(role)
        if op["id"][0] != letter:
            return None                                       # you cannot draw as the other person
        existing = self.by_id.get(op["id"])
        if op["kind"] == "text":
            if existing is not None or len(self.ops) >= MAX_OPS:
                return None
            return self._add(letter, op)
        if existing is None:
            points = op["points"][:MAX_STROKE_POINTS]
            if len(self.ops) >= MAX_OPS or self.points + len(points) > MAX_TOTAL_POINTS:
                return None
            return self._add(letter, dict(op, points=points))
        if existing["kind"] != "stroke":
            return None
        room = MAX_STROKE_POINTS - len(existing["points"])
        new = op["points"][:max(0, room)]
        if not new or self.points + len(new) > MAX_TOTAL_POINTS:
            return None
        existing["points"].extend(new)
        self.points += len(new)
        return dict(op, points=[p[:] for p in new])

    def undo(self, role):
        """Remove your latest item. Returns its id, or None if you have nothing to undo."""
        letter = self._letter(role)
        for i in range(len(self.ops) - 1, -1, -1):
            if self.ops[i]["id"][0] == letter:
                op = self.ops.pop(i)
                del self.by_id[op["id"]]
                if op["kind"] == "stroke":
                    self.points -= len(op["points"])
                stack = self.redo_stacks[letter]
                stack.append(op)
                del stack[:-MAX_REDO]
                return op["id"]
        return None

    def redo(self, role):
        """Put back the item you last undid. Returns it, or None."""
        letter = self._letter(role)
        stack = self.redo_stacks[letter]
        if not stack:
            return None
        op = stack[-1]
        extra = len(op["points"]) if op["kind"] == "stroke" else 0
        if len(self.ops) >= MAX_OPS or self.points + extra > MAX_TOTAL_POINTS:
            return None
        stack.pop()
        self.ops.append(op)
        self.by_id[op["id"]] = op
        self.points += extra
        return _public(op)

    def clear(self, role):
        self.ops, self.by_id, self.points = [], {}, 0
        for stack in self.redo_stacks.values():
            stack.clear()
        return True

    def snapshot(self):
        return [_public(op) for op in self.ops]
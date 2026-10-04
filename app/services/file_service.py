"""Files shared inside a live session. We never trust the file name or the browser's file type:
the contents must really be one of the allowed kinds, the stored name is random, and files live
outside app/static so they are only ever served to the two people of that session."""
import io
import os
import re
import secrets
import unicodedata
import zipfile
from pathlib import Path

from flask import current_app
from PIL import Image

from app.db import execute, query_all, query_one
from app.timeutil import utcnow

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_FILES = 20
MAX_TOTAL_BYTES = 25 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_NAME = 100
MAX_ENTRIES = 2000                      # a DOCX or PPTX is a ZIP: refuse absurd ones
MAX_UNPACKED = 100 * 1024 * 1024
IMAGE_KINDS = ("jpeg", "png", "webp", "gif")

# kind -> (allowed extensions, extension we store, content type we serve)
KINDS = {
    "pdf": ({".pdf"}, ".pdf", "application/pdf"),
    "docx": ({".docx"}, ".docx",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "pptx": ({".pptx"}, ".pptx",
             "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    "jpeg": ({".jpg", ".jpeg"}, ".jpg", "image/jpeg"),
    "png": ({".png"}, ".png", "image/png"),
    "webp": ({".webp"}, ".webp", "image/webp"),
    "gif": ({".gif"}, ".gif", "image/gif"),
    "txt": ({".txt"}, ".txt", "text/plain; charset=utf-8"),
}
ALLOWED_EXT = {ext for exts, _c, _m in KINDS.values() for ext in exts}
NAME_RE = re.compile(r"^[0-9a-f]{32}\.(pdf|docx|pptx|jpg|png|webp|gif|txt)$")   # the ONLY names we serve
TYPE_HELP = ("This file type is not allowed. You can share PDF, DOCX, PPTX, images "
             "(JPG, PNG, WebP, GIF) and TXT files.")
UNREADABLE = "That image could not be read. Please choose a different file."


class FileError(Exception):
    """The message is always safe to show to the user."""


# ---------- rules (no database) ----------
def human_size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{round(n / 1024)} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def sanitize_name(raw):
    """A safe display name: no folders, no control or invisible characters, no characters that
    Windows forbids, no leading or trailing dots, at most 100 characters."""
    name = (raw or "").replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    name = re.sub(r'[<>:"|?*]', "_", name)
    name = " ".join(name.split()).strip(". ")
    if len(name) > MAX_NAME:
        stem, ext = os.path.splitext(name)
        name = stem[:MAX_NAME - len(ext)] + ext
    return name


def office_kind(data):
    """'docx' or 'pptx' if this ZIP really is one (and has no macros), else None."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_UNPACKED:
                return None
            names = {i.filename for i in infos}
    except Exception:
        return None
    if any("vbaproject" in n.lower() for n in names):
        return None                                    # macro-enabled documents are refused
    if "[Content_Types].xml" in names and "word/document.xml" in names:
        return "docx"
    if "[Content_Types].xml" in names and "ppt/presentation.xml" in names:
        return "pptx"
    return None


def looks_like_text(data):
    if not data or b"\x00" in data:
        return False
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    return all(ch in "\t\n\r" or (ord(ch) >= 32 and ch != "\x7f") for ch in text)


def detect_kind(data):
    """The REAL type from the contents (first bytes, then deeper checks), or None."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        return office_kind(data)
    return "txt" if looks_like_text(data) else None


def verify_image(data):
    try:
        img = Image.open(io.BytesIO(data))
        width, height = img.size
    except Exception:
        raise FileError(UNREADABLE) from None
    if width * height > MAX_PIXELS:
        raise FileError("That image has too many pixels. Please choose a smaller one.")
    try:
        img.verify()
    except Exception:
        raise FileError(UNREADABLE) from None


def validate_upload(filename, data):
    """Returns (kind, display_name) or raises FileError."""
    name = sanitize_name(filename)
    if not name:
        raise FileError("Choose a file to upload.")
    if not data:
        raise FileError("That file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise FileError("That file is too large. The limit is 5 MB.")
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise FileError(TYPE_HELP)
    kind = detect_kind(data)
    if kind is None or ext not in KINDS[kind][0]:
        raise FileError("The file's contents do not match its type, so it was not accepted.")
    if kind in IMAGE_KINDS:
        verify_image(data)
    return kind, name


# ---------- disk ----------
def files_dir():
    base = Path(current_app.config["UPLOAD_FOLDER"])
    if not base.is_absolute():
        base = Path(current_app.root_path).parent / base
    folder = base / "session_files"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def store(kind, data):
    name = secrets.token_hex(16) + KINDS[kind][1]
    (files_dir() / name).write_bytes(data)
    return name


def delete_stored(name):
    """Deletes only files whose name matches our own pattern (no path tricks)."""
    if name and NAME_RE.match(name):
        (files_dir() / name).unlink(missing_ok=True)


# ---------- database ----------
def totals(request_id):
    return query_one("SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS total "
                     "FROM session_files WHERE request_id = %s", (request_id,))


def check_limits(request_id, size):
    used = totals(request_id)
    if used["n"] >= MAX_FILES:
        raise FileError(f"This session already has {MAX_FILES} files. Remove one to add another.")
    if int(used["total"]) + size > MAX_TOTAL_BYTES:
        raise FileError("This session has reached its 25 MB file limit. Remove a file to add another.")


def add_file(request_id, user_id, original_name, stored_name, kind, size):
    return execute("INSERT INTO session_files (request_id, user_id, original_name, stored_name, "
                   "kind, size_bytes, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                   (request_id, user_id, original_name, stored_name, kind, size, utcnow()))


def list_files(request_id):
    rows = query_all(
        "SELECT f.id, f.original_name, f.kind, f.size_bytes, f.created_at, u.full_name AS uploader, "
        "CASE WHEN f.user_id = r.tutor_id THEN 'tutor' ELSE 'student' END AS role "
        "FROM session_files f JOIN users u ON u.id = f.user_id "
        "JOIN tutoring_requests r ON r.id = f.request_id WHERE f.request_id = %s ORDER BY f.id",
        (request_id,))
    for row in rows:
        row["size_label"] = human_size(row["size_bytes"])
    return rows


def get_file(request_id, file_id):
    return query_one("SELECT id, user_id, original_name, stored_name, kind, size_bytes "
                     "FROM session_files WHERE id = %s AND request_id = %s", (file_id, request_id))


def delete_row(file_id, request_id, user_id):
    """user_id in WHERE: only the uploader's own file can be removed."""
    execute("DELETE FROM session_files WHERE id = %s AND request_id = %s AND user_id = %s",
            (file_id, request_id, user_id))


def save_upload(request_id, user_id, uploader_name, role, filename, data):
    """Check, store and register one upload. Returns the new file's details."""
    kind, display_name = validate_upload(filename, data)
    check_limits(request_id, len(data))
    stored = store(kind, data)
    try:
        file_id = add_file(request_id, user_id, display_name, stored, kind, len(data))
    except Exception:
        delete_stored(stored)                              # do not leave an orphan file behind
        raise
    return {"id": file_id, "original_name": display_name, "kind": kind, "size_bytes": len(data),
            "size_label": human_size(len(data)), "created_at": utcnow(),
            "uploader": uploader_name, "role": role}
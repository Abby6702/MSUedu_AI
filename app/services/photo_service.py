"""Photo checking and storage. We never trust the file name or the browser's file type:
the bytes must really be a JPEG, PNG or WebP image, and we re-encode it ourselves, which
drops any hidden data (such as GPS location) and anything that is not pixels."""
import io
import re
import secrets
from pathlib import Path

from flask import current_app
from PIL import Image, ImageOps

from app.services import people_service

MAX_BYTES = 700 * 1024
MAX_PIXELS = 16_000_000
MIN_SIDE = 100
OUT_SIZE = 400
NAME_RE = re.compile(r"^[0-9a-f]{32}\.jpg$")        # the ONLY file names we create or serve
UNREADABLE = "That file could not be read as an image. Please choose a different photo."
WRONG_TYPE = "Only JPEG, PNG or WebP photos are allowed."


class PhotoError(Exception):
    """The message is always safe to show to the user."""


def sniff(data):
    """The real type from the first bytes ('magic numbers'), or None."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def process_image(data):
    """Validate an uploaded image and return clean 400x400 JPEG bytes, or raise PhotoError."""
    if not data:
        raise PhotoError("Choose a photo to upload.")
    if len(data) > MAX_BYTES:
        raise PhotoError("That photo is too large. Please choose one under 700 KB.")
    if sniff(data) is None:
        raise PhotoError(WRONG_TYPE)
    try:
        img = Image.open(io.BytesIO(data))
        fmt, (width, height) = img.format, img.size
    except Exception:
        raise PhotoError(UNREADABLE) from None
    if fmt not in ("JPEG", "PNG", "WEBP"):
        raise PhotoError(WRONG_TYPE)
    if width * height > MAX_PIXELS:
        raise PhotoError("That photo has too many pixels. Please choose a smaller one.")
    if min(width, height) < MIN_SIDE:
        raise PhotoError("That photo is too small. It must be at least 100 pixels on each side.")
    try:
        img.load()                                           # decodes the whole image
        img = ImageOps.exif_transpose(img)                   # honour the camera's rotation
        if img.mode in ("RGBA", "LA", "P"):                  # flatten transparency onto white
            rgba = img.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.getchannel("A"))
            img = background
        else:
            img = img.convert("RGB")
        img = ImageOps.fit(img, (OUT_SIZE, OUT_SIZE), Image.LANCZOS)    # centred square crop
        out = io.BytesIO()
        img.save(out, "JPEG", quality=85, optimize=True)     # a NEW file: no metadata copied over
    except Exception:
        raise PhotoError(UNREADABLE) from None
    return out.getvalue()


def photo_dir():
    base = Path(current_app.config["UPLOAD_FOLDER"])
    if not base.is_absolute():
        base = Path(current_app.root_path).parent / base
    folder = base / "profile_photos"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def delete_file(name):
    """Deletes only files whose name matches our own pattern (no path tricks)."""
    if name and NAME_RE.match(name):
        (photo_dir() / name).unlink(missing_ok=True)


def save_photo(tutor_id, jpeg_bytes):
    """Write the file under a random name, point the profile at it, remove the old file."""
    old = (people_service.get_details(tutor_id) or {}).get("photo_filename")
    name = secrets.token_hex(16) + ".jpg"
    path = photo_dir() / name
    path.write_bytes(jpeg_bytes)
    try:
        people_service.set_photo(tutor_id, name)
    except Exception:
        path.unlink(missing_ok=True)                         # do not leave an orphan file behind
        raise
    delete_file(old)
    return name


def remove_photo(tutor_id):
    old = (people_service.get_details(tutor_id) or {}).get("photo_filename")
    people_service.set_photo(tutor_id, None)
    delete_file(old)
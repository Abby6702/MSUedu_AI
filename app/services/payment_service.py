"""Private payment-proof storage and validation."""
import mimetypes
import re
import secrets
from pathlib import Path

from flask import current_app

from app.services import file_service

PROOF_KINDS = ("pdf", "jpeg", "png", "webp")
PROOF_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(pdf|jpg|png|webp)$")


def validate_proof(filename, data):
    kind, _display_name = file_service.validate_upload(filename, data)
    if kind not in PROOF_KINDS:
        raise file_service.FileError("Payment proof must be a PDF or image (JPG, PNG or WebP).")
    return kind


def proofs_dir():
    base = Path(current_app.config["UPLOAD_FOLDER"])
    if not base.is_absolute():
        base = Path(current_app.root_path).parent / base
    folder = base / "payment_proofs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def store_proof(kind, data):
    if kind not in PROOF_KINDS:
        raise ValueError("Unsupported payment-proof kind.")
    extension = file_service.KINDS[kind][1]
    name = secrets.token_hex(16) + extension
    (proofs_dir() / name).write_bytes(data)
    return name


def remove_proof(name):
    if name and PROOF_NAME_RE.fullmatch(name):
        (proofs_dir() / name).unlink(missing_ok=True)


def proof_mimetype(name):
    return mimetypes.guess_type(name)[0] or "application/octet-stream"

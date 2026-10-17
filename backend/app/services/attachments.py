"""Secure attachment storage.

- Extension allow-list AND magic-byte verification (content must match the extension)
- Size limit enforced while streaming
- Stored outside the web root under a random name; original name kept only as metadata
- Downloads go through an authorised endpoint with Content-Disposition: attachment
"""
import hashlib
import os
import re
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.errors import BusinessRuleError

ALLOWED: dict[str, tuple[str, tuple[bytes, ...] | None]] = {
    ".png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    ".jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".gif": ("image/gif", (b"GIF87a", b"GIF89a")),
    ".pdf": ("application/pdf", (b"%PDF-",)),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", (b"PK\x03\x04",)),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", (b"PK\x03\x04",)),
    ".txt": ("text/plain", None),
    ".log": ("text/plain", None),
    ".csv": ("text/csv", None),
}
MAX_FILES_PER_TICKET = 20


def safe_display_name(name: str) -> str:
    base = os.path.basename(name or "file").strip().replace("\x00", "")
    base = re.sub(r"[^\w.\- ()]+", "_", base)[:200]
    return base or "file"


def _verify_magic(ext: str, head: bytes) -> None:
    sigs = ALLOWED[ext][1]
    if sigs is None:
        if b"\x00" in head:
            raise BusinessRuleError("Text files must not contain binary data.")
        try:
            head.decode("utf-8")
        except UnicodeDecodeError:
            # head may cut a multi-byte char; accept if only the tail is invalid
            try:
                head[:-4].decode("utf-8")
            except UnicodeDecodeError:
                raise BusinessRuleError("Text files must be UTF-8 encoded.")
        return
    if not any(head.startswith(s) for s in sigs):
        raise BusinessRuleError("File content does not match its extension.")


async def store_upload(file: UploadFile) -> dict:
    s = get_settings()
    name = safe_display_name(file.filename or "")
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED:
        raise BusinessRuleError(f"File type not allowed. Allowed: {', '.join(sorted(ALLOWED))}")
    limit = s.max_upload_mb * 1024 * 1024
    root = Path(s.upload_dir).resolve()
    stored = f"{uuid.uuid4().hex}{ext}"
    sub = root / stored[:2]
    sub.mkdir(parents=True, exist_ok=True)
    dest = sub / stored
    sha, size, head = hashlib.sha256(), 0, b""
    try:
        with open(dest, "wb") as out:
            while chunk := await file.read(64 * 1024):
                if not head:
                    head = chunk[:512]
                    _verify_magic(ext, head)
                size += len(chunk)
                if size > limit:
                    raise BusinessRuleError(f"File exceeds the {s.max_upload_mb} MB limit.")
                sha.update(chunk)
                out.write(chunk)
        if size == 0:
            raise BusinessRuleError("Empty files are not allowed.")
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return {"original_name": name, "stored_name": stored, "content_type": ALLOWED[ext][0],
            "size_bytes": size, "sha256": sha.hexdigest()}


def path_for(stored_name: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}\.[a-z]{3,4}", stored_name):
        raise BusinessRuleError("Invalid attachment reference.")
    root = Path(get_settings().upload_dir).resolve()
    p = (root / stored_name[:2] / stored_name).resolve()
    if root not in p.parents:
        raise BusinessRuleError("Invalid attachment reference.")
    return p

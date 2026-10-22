"""Secure attachment storage.

- Extension allow-list AND magic-byte verification (content must match the extension)
- Size limit enforced while streaming
- Stored outside the web root under a random name; original name kept only as metadata
- Downloads go through an authorised endpoint with Content-Disposition: attachment
"""
import hashlib
import io
import os
import re
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.errors import BusinessRuleError

# Images and PDF only. SVG is deliberately excluded (it can carry scripts).
ALLOWED: dict[str, tuple[str, tuple[bytes, ...]]] = {
    ".png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    ".jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".gif": ("image/gif", (b"GIF87a", b"GIF89a")),
    ".webp": ("image/webp", (b"RIFF",)),
    ".bmp": ("image/bmp", (b"BM",)),
    ".tif": ("image/tiff", (b"II*\x00", b"MM\x00*")),
    ".tiff": ("image/tiff", (b"II*\x00", b"MM\x00*")),
    ".heic": ("image/heic", ()),
    ".heif": ("image/heif", ()),
    ".pdf": ("application/pdf", (b"%PDF-",)),
}
MAX_FILES_PER_TICKET = 20


def safe_display_name(name: str) -> str:
    base = os.path.basename(name or "file").strip().replace("\x00", "")
    base = re.sub(r"[^\w.\- ()]+", "_", base)[:200]
    return base or "file"


def _verify_magic(ext: str, head: bytes) -> None:
    ok = False
    if ext in (".heic", ".heif"):  # ISO-BMFF: bytes 4..12 = 'ftyp' + brand
        ok = head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1")
    elif ext == ".webp":
        ok = head.startswith(b"RIFF") and head[8:12] == b"WEBP"
    else:
        ok = any(head.startswith(sig) for sig in ALLOWED[ext][1])
    if not ok:
        raise BusinessRuleError("File content does not match its extension. Only images and PDF files are allowed.")


async def store_upload(file: UploadFile) -> dict:
    """Validate and store an upload. Returns metadata; with ATTACHMENT_STORAGE=database the
    bytes are returned under "data" for the caller to save in ticket_attachment_blobs."""
    s = get_settings()
    name = safe_display_name(file.filename or "")
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED:
        raise BusinessRuleError("Only images (PNG, JPG, GIF, WEBP, BMP, TIFF, HEIC) and PDF files can be attached.")
    limit = s.max_upload_mb * 1024 * 1024
    stored = f"{uuid.uuid4().hex}{ext}"
    in_db = s.attachment_storage == "database"
    buf = io.BytesIO()
    dest = None
    if not in_db:
        root = Path(s.upload_dir).resolve()
        (root / stored[:2]).mkdir(parents=True, exist_ok=True)
        dest = root / stored[:2] / stored
    sha, size, head = hashlib.sha256(), 0, b""
    try:
        out = buf if in_db else open(dest, "wb")
        try:
            while chunk := await file.read(64 * 1024):
                if not head:
                    head = chunk[:512]
                    _verify_magic(ext, head)
                size += len(chunk)
                if size > limit:
                    raise BusinessRuleError(f"File exceeds the {s.max_upload_mb} MB limit.")
                sha.update(chunk)
                out.write(chunk)
        finally:
            if not in_db:
                out.close()
        if size == 0:
            raise BusinessRuleError("Empty files are not allowed.")
    except Exception:
        if dest is not None:
            dest.unlink(missing_ok=True)
        raise
    meta = {"original_name": name, "stored_name": stored, "content_type": ALLOWED[ext][0],
            "size_bytes": size, "sha256": sha.hexdigest()}
    if in_db:
        meta["data"] = buf.getvalue()
    return meta


def path_for(stored_name: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}\.[a-z]{3,4}", stored_name):
        raise BusinessRuleError("Invalid attachment reference.")
    root = Path(get_settings().upload_dir).resolve()
    p = (root / stored_name[:2] / stored_name).resolve()
    if root not in p.parents:
        raise BusinessRuleError("Invalid attachment reference.")
    return p

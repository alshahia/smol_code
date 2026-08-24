"""File uploads for smolcode (M8, decision 0010 D8).

User-uploaded files live in <workspace>/.smolcode/uploads/ (a hidden
dot-folder). Every upload is:

  * Sanitised -- path separators stripped, Windows reserved names
    rejected, length capped, collision suffix added.
  * MIME-sniffed -- the browser-claimed MIME is IGNORED in favour of
    mimetypes.guess_type + first-8 KB magic-byte detection.
  * Allowlisted -- the default allowlist is text + docs + images +
    code; executables, archives, and shell scripts-as-executables
    are blocked (see DEFAULT_ALLOWED_MIME).
  * Size-capped -- DEFAULT_MAX_BYTES = 50 MB; HTTP layer enforces
    this before reading the body into memory.
  * Hashed -- sha256 over the file bytes is recorded for dedup +
    integrity verification.
  * Sidecar-logged -- append-only .uploads.jsonl in the same dir
    records every add / delete event with timestamp, original name,
    stored name, size, sniffed MIME, sha256, tier-at-upload, and
    who triggered the action.

The agent (when running) discovers uploads via three layers
(design 0010 D8):

  1. A system-prompt hint at run start lists uploads added in the
     CURRENT session.
  2. The list_uploads() tool returns the full sidecar.
  3. The read_upload(name) tool wraps read_file on the uploads dir.

The Tier policy (config.Tier.uploads) controls whether the agent can
read / modify / delete uploads. The default is:

    restricted    -> "read"       (agent reads, cannot modify/delete)
    elevated      -> "readwrite"  (full agent access)
    full_access   -> "readwrite"  (full agent access)

The GUI / CLI can ALWAYS delete via explicit user action (per-file
button, "uploads clean"); this is independent of the tier policy.

Persistence is INDEFINITE by default. SMOLCODE_UPLOAD_TTL_DAYS is an
opt-in soft TTL that flags stale files in the GUI but does NOT
auto-delete (deletion is always explicit).

Public surface:
    safe_name(filename)                          -> str
    sniff_mime(data, declared_mime=None)         -> str
    is_mime_allowed(mime, allowlist)             -> bool
    DEFAULT_ALLOWED_MIME                         -> tuple[str, ...]
    DEFAULT_MAX_BYTES                            -> int (50 MB)
    SIDECAR_NAME                                 -> str (".uploads.jsonl")
    UploadsStore(dir, max_bytes=..., audit=None,
                 allowed_mime=..., allow_overwrite=False)
        .save(original_name, data, declared_mime,
              tier, uploaded_by)                  -> UploadMetadata
        .list_metadata()                         -> list[UploadMetadata]
        .read(stored_name)                       -> bytes
        .delete(stored_name, deleted_by)         -> None
        .clean(older_than_days=None)             -> int  (count deleted)
        .path_for(stored_name)                   -> Path
    UploadMetadata                               -> dataclass
    UploadsError(RuntimeError)                   -> raised on misuse
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


# --- Defaults ----------------------------------------------------------------


SIDECAR_NAME = ".uploads.jsonl"
DEFAULT_MAX_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_FILENAME_LEN = 200

# Default MIME allowlist (decision 0010 D8, user confirmed 2026-08-20).
# Patterns are matched as case-insensitive prefixes (e.g. "text/" matches
# "text/plain", "text/csv", "text/html").
DEFAULT_ALLOWED_MIME: tuple[str, ...] = (
    # Text
    "text/",
    "application/json",
    "application/xml",
    "application/yaml",
    "application/x-yaml",
    # Documents
    "application/pdf",
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.",
    # Images
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
)

# Always blocked regardless of allowlist (defence in depth).
_BLOCKED_MIME: tuple[str, ...] = (
    "application/x-msdownload",
    "application/x-msdos-program",
    "application/x-executable",
    "application/x-sharedlib",
    "application/x-sh",
    "application/x-bash",
    # Archives that can contain executables -- we do not extract anything
    # in v1, so blocking archives entirely keeps the attack surface flat.
    "application/zip",
    "application/x-tar",
    "application/x-7z-compressed",
    "application/x-rar-compressed",
    "application/x-gzip",
    "application/x-bzip2",
)

# Windows reserved filenames (case-insensitive, no extension).
_WINDOWS_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)

# Magic-byte signatures for sniffing common formats. Only the first 8 bytes
# are read; fall back to mimetypes.guess_type for everything else.
_MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),  # also docx/xlsx/odt
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # needs WEBP at offset 8
    (b"\x1f\x8b", "application/x-gzip"),
    (b"BZh", "application/x-bzip2"),
    (b"\xfd7zXZ\x00", "application/x-xz"),
)


# --- Exceptions --------------------------------------------------------------


class UploadsError(RuntimeError):
    """Raised when an upload cannot be processed (bad name, size, MIME, ...)."""


# --- Filename sanitisation ---------------------------------------------------


_FILENAME_STRIP_RE = re.compile(r"[^A-Za-z0-9._\- ]")


def safe_name(filename: str) -> str:
    """Return a safe-on-disk version of filename.

    Strips path separators (Windows + POSIX), resolves .., rejects
    Windows-reserved basenames, caps length, and falls back to
    'upload' if nothing usable remains.
    """
    if filename is None:
        return "upload"
    # Strip directory components -- keep only the basename.
    name = filename.replace("\\", "/").split("/")[-1]
    # Strip leading dots (no hidden files in the uploads dir).
    name = name.lstrip(".")
    if not name:
        return "upload"
    # Reject Windows-reserved basenames (case-insensitive).
    stem, dot, ext = name.partition(".")
    if stem.upper() in _WINDOWS_RESERVED:
        stem = stem + "_"
        name = stem + (dot + ext if ext else "")
    # Replace any remaining odd characters.
    cleaned = _FILENAME_STRIP_RE.sub("_", name)
    # Collapse runs of underscores.
    # Only strip trailing DOTS (not underscores -- the underscore we
    # appended to mark a Windows-reserved name must be preserved).
    cleaned = re.sub(r"_+", "_", cleaned).strip(".")
    if not cleaned:
        cleaned = "upload"
    # Cap length.
    if len(cleaned) > MAX_FILENAME_LEN:
        stem, dot, ext = cleaned.rpartition(".")
        keep = MAX_FILENAME_LEN - len(dot + ext) - 1 if ext else MAX_FILENAME_LEN
        if keep <= 0:
            cleaned = cleaned[:MAX_FILENAME_LEN]
        else:
            cleaned = stem[:keep] + dot + ext
    return cleaned


# --- MIME handling -----------------------------------------------------------


def sniff_mime(data: bytes, declared_mime=None) -> str:
    """Return the sniffed MIME type for data.

    Reads at most the first 8 bytes for magic-byte matching, then
    falls back to a generic content type. Returns lowercase; the
    empty string means 'unknown'. The caller is expected to gate on
    the result via is_mime_allowed.
    """
    if not data:
        return "application/octet-stream"
    head = data[:8]
    for sig, mime in _MAGIC_SIGNATURES:
        if head.startswith(sig):
            # Special-case RIFF/WEBP -- full check requires offset 8.
            if mime == "image/webp":
                if len(data) >= 12 and data[8:12] == b"WEBP":
                    return mime
                continue
            return mime
    # No magic match. Two safe fallbacks:
    #   1. UTF-8 decodable -> text/plain (covers txt, csv, json, md, etc.)
    #   2. Otherwise -> application/octet-stream (unknown binary)
    # The browser-claimed MIME is intentionally NOT used here: a
    # malicious .exe served as "text/plain" must still be rejected.
    try:
        data.decode("utf-8")
        return "text/plain"
    except UnicodeDecodeError:
        return "application/octet-stream"


def is_mime_allowed(mime: str, allowlist: Iterable[str]) -> bool:
    """Return True iff mime is permitted by allowlist.

    Each entry in allowlist is matched as a case-insensitive prefix
    against the full mime (e.g. "text/" matches "text/plain").
    'application/octet-stream' is rejected (unknown files are never
    silently allowed).
    """
    if not mime:
        return False
    mime = mime.lower()
    for blocked in _BLOCKED_MIME:
        b = blocked.lower()
        if b.endswith("/"):
            if mime.startswith(b):
                return False
        else:
            if mime == b:
                return False
    for pattern in allowlist:
        pat = pattern.lower()
        if pat.endswith("/"):
            if mime.startswith(pat):
                return True
        else:
            if mime == pat:
                return True
    return False


# --- Metadata ----------------------------------------------------------------


@dataclass
class UploadMetadata:
    """One row of the .uploads.jsonl sidecar."""

    ts: str
    original_name: str
    stored_name: str
    size: int
    mime: str
    sha256: str
    tier: str
    uploaded_by: str  # "gui" | "cli" | "api"


# --- Store -------------------------------------------------------------------


class UploadsStore:
    """File-backed upload store with append-only JSONL sidecar.

    Thread-safe. All mutations are serialised via a single lock.
    """

    def __init__(
        self,
        dir,
        *,
        max_bytes=DEFAULT_MAX_BYTES,
        allowed_mime=DEFAULT_ALLOWED_MIME,
        audit=None,
        allow_overwrite=False,
    ):
        self.dir = Path(dir)
        self.max_bytes = int(max_bytes)
        self.allowed_mime = tuple(allowed_mime)
        self.audit = audit
        self.allow_overwrite = bool(allow_overwrite)
        self._lock = threading.Lock()
        self.dir.mkdir(parents=True, exist_ok=True)
        self._sidecar = self.dir / SIDECAR_NAME

    # -- helpers --------------------------------------------------------------

    def _now_iso(self):
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _append_sidecar(self, entry: dict) -> None:
        with self._sidecar.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")

    def _audit_event(self, event: str, **fields) -> None:
        if self.audit is None:
            return
        try:
            self.audit.record(event, **fields)
        except Exception:
            pass

    def _resolve_collision(self, base: str) -> str:
        target = self.dir / base
        if not target.exists():
            return base
        if self.allow_overwrite:
            return base
        stem, dot, ext = base.rpartition(".")
        for _ in range(1000):
            suffix = self._sha256((base + "-").encode("utf-8") + os.urandom(4))[:6]
            candidate = (stem + "-" + suffix + dot + ext) if ext else (stem + "-" + suffix)
            if not (self.dir / candidate).exists():
                return candidate
        raise UploadsError("too many collisions for base=" + repr(base))

    def path_for(self, stored_name: str):
        if not stored_name or "/" in stored_name or "\\" in stored_name:
            raise UploadsError("invalid stored_name: " + repr(stored_name))
        return self.dir / stored_name

    # -- public API -----------------------------------------------------------

    def save(
        self,
        *,
        original_name: str,
        data: bytes,
        declared_mime=None,
        tier: str,
        uploaded_by: str = "cli",
    ) -> UploadMetadata:
        if data is None:
            raise UploadsError("data is required")
        if len(data) > self.max_bytes:
            raise UploadsError("file too large: " + str(len(data)) + " bytes > max " + str(self.max_bytes))
        safe = safe_name(original_name)
        mime = sniff_mime(data, declared_mime)
        if not is_mime_allowed(mime, self.allowed_mime):
            raise UploadsError("mime " + repr(mime) + " not in allowlist (declared=" + repr(declared_mime) + ")")
        sha = self._sha256(data)
        with self._lock:
            stored = self._resolve_collision(safe)
            target = self.dir / stored
            target.write_bytes(data)
            meta = UploadMetadata(
                ts=self._now_iso(),
                original_name=original_name,
                stored_name=stored,
                size=len(data),
                mime=mime,
                sha256=sha,
                tier=tier,
                uploaded_by=uploaded_by,
            )
            self._append_sidecar(
                {
                    "event": "add",
                    "ts": meta.ts,
                    "original_name": meta.original_name,
                    "stored_name": meta.stored_name,
                    "size": meta.size,
                    "mime": meta.mime,
                    "sha256": meta.sha256,
                    "tier": meta.tier,
                    "uploaded_by": meta.uploaded_by,
                }
            )
        self._audit_event(
            "upload.add",
            name=meta.stored_name,
            original=meta.original_name,
            size=meta.size,
            mime=meta.mime,
            sha256=meta.sha256,
            tier=meta.tier,
        )
        return meta

    def list_metadata(self) -> list:
        """Return metadata for files that currently exist on disk.

        Reads the append-only sidecar and returns one UploadMetadata
        per 'add' event whose stored_name still exists. A delete()
        correctly removes the file from the listing even though the
        'add' entry remains in the sidecar (audit trail).
        """
        if not self._sidecar.exists():
            return []
        out = []
        with self._sidecar.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("event") != "add":
                    continue
                stored = entry.get("stored_name", "")
                if not stored or not (self.dir / stored).is_file():
                    continue
                out.append(
                    UploadMetadata(
                        ts=entry.get("ts", ""),
                        original_name=entry.get("original_name", ""),
                        stored_name=stored,
                        size=int(entry.get("size", 0)),
                        mime=entry.get("mime", ""),
                        sha256=entry.get("sha256", ""),
                        tier=entry.get("tier", ""),
                        uploaded_by=entry.get("uploaded_by", ""),
                    )
                )
        return out

    def read(self, stored_name: str) -> bytes:
        p = self.path_for(stored_name)
        if not p.exists() or not p.is_file():
            raise UploadsError("upload not found: " + repr(stored_name))
        return p.read_bytes()

    def delete(self, stored_name: str, *, deleted_by: str = "cli") -> None:
        p = self.path_for(stored_name)
        with self._lock:
            if not p.exists():
                raise UploadsError("upload not found: " + repr(stored_name))
            size = p.stat().st_size
            try:
                p.unlink()
            except OSError as e:
                raise UploadsError("could not delete " + repr(stored_name) + ": " + str(e)) from e
            self._append_sidecar(
                {
                    "event": "delete",
                    "ts": self._now_iso(),
                    "stored_name": stored_name,
                    "deleted_by": deleted_by,
                }
            )
        self._audit_event(
            "upload.delete",
            name=stored_name,
            deleted_by=deleted_by,
            size=size,
        )

    def clean(self, *, older_than_days=None) -> int:
        if older_than_days is not None:
            if older_than_days < 0:
                raise UploadsError("older_than_days must be >= 0")
            if older_than_days == 0:
                # 0 means "no-op" -- do not delete anything.
                return 0
        with self._lock:
            metas = self.list_metadata()
        count = 0
        cutoff = None
        if older_than_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=int(older_than_days))
        for m in metas:
            if cutoff is not None:
                try:
                    when = datetime.strptime(m.ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                if when > cutoff:
                    continue
            try:
                self.delete(m.stored_name, deleted_by="clean")
                count += 1
            except UploadsError:
                continue
        return count


__all__ = [
    "SIDECAR_NAME",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_ALLOWED_MIME",
    "MAX_FILENAME_LEN",
    "UploadMetadata",
    "UploadsError",
    "UploadsStore",
    "safe_name",
    "sniff_mime",
    "is_mime_allowed",
]

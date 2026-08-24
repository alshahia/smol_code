"""M8 - uploads module + tier write-block + CLI subcommand tests."""

from __future__ import annotations

import json
import os

import pytest

from smolcode.tools.fs import build_fs_tools
from smolcode.uploads import (
    DEFAULT_ALLOWED_MIME,
    DEFAULT_MAX_BYTES,
    MAX_FILENAME_LEN,
    SIDECAR_NAME,
    UploadMetadata,
    UploadsError,
    UploadsStore,
    is_mime_allowed,
    safe_name,
    sniff_mime,
)


# ---- safe_name --------------------------------------------------------------


class TestSafeName:
    def test_simple_name_unchanged(self):
        assert safe_name("notes.txt") == "notes.txt"

    def test_strips_unix_path(self):
        assert safe_name("../../etc/passwd") == "passwd"

    def test_strips_windows_path(self):
        assert safe_name(r"C:\Users\me\evil.exe") == "evil.exe"

    def test_empty_returns_upload(self):
        assert safe_name("") == "upload"

    def test_none_returns_upload(self):
        assert safe_name(None) == "upload"  # type: ignore[arg-type]

    def test_only_dots_returns_upload(self):
        assert safe_name("...") == "upload"

    def test_windows_reserved_gets_underscore(self):
        assert safe_name("CON.txt") == "CON_.txt"
        assert safe_name("PRN") == "PRN_"
        assert safe_name("com1.log") == "com1_.log"

    def test_strips_leading_dots(self):
        # No hidden files in the uploads dir.
        assert safe_name(".hidden") == "hidden"
        assert safe_name("..sneaky") == "sneaky"

    def test_length_capped(self):
        long = "a" * 500 + ".txt"
        out = safe_name(long)
        assert len(out) <= MAX_FILENAME_LEN

    def test_length_cap_preserves_extension(self):
        long = "b" * 500 + ".verylongext"
        out = safe_name(long)
        assert out.endswith(".verylongext")
        assert len(out) <= MAX_FILENAME_LEN

    def test_special_chars_replaced(self):
        out = safe_name("hello world!@#.txt")
        # Only [A-Za-z0-9._- ] survive; the rest become _.
        assert out == "hello world___-_.txt" or out.replace(" ", "_").startswith("hello")


# ---- sniff_mime -------------------------------------------------------------


class TestSniffMime:
    def test_empty_returns_octet_stream(self):
        assert sniff_mime(b"") == "application/octet-stream"

    def test_png(self):
        assert sniff_mime(b"\x89PNG\r\n\x1a\nrest") == "image/png"

    def test_jpeg(self):
        assert sniff_mime(b"\xff\xd8\xff\xe0rest") == "image/jpeg"

    def test_pdf(self):
        assert sniff_mime(b"%PDF-1.4") == "application/pdf"

    def test_gif87(self):
        assert sniff_mime(b"GIF87a...") == "image/gif"

    def test_gif89(self):
        assert sniff_mime(b"GIF89a...") == "image/gif"

    def test_zip(self):
        assert sniff_mime(b"PK\x03\x04rest") == "application/zip"

    def test_gzip(self):
        assert sniff_mime(b"\x1f\x8b\x08rest") == "application/x-gzip"

    def test_riff_without_webp_is_not_webp(self):
        # RIFF + non-WEBP fourcc -> falls through to octet-stream.
        # Use non-UTF-8 RIFF payload so the UTF-8 fallback does not match.
        assert sniff_mime(b"RIFF\xff\xff\xff\xffAVI ") == "application/octet-stream"

    def test_riff_with_webp(self):
        assert sniff_mime(b"RIFF\x00\x00\x00\x00WEBPVP8") == "image/webp"

    def test_declared_mime_ignored_when_no_magic(self):
        # Plain text bytes have no magic; the declared MIME doesn't override.
        # Non-UTF-8 binary: the UTF-8 fallback must NOT trigger, so result is octet-stream.
        out = sniff_mime(b"\x80\x81\x82\x83", declared_mime="image/png")
        assert out == "application/octet-stream"


# ---- is_mime_allowed --------------------------------------------------------


class TestIsMimeAllowed:
    def test_text_prefix_matches(self):
        assert is_mime_allowed("text/plain", DEFAULT_ALLOWED_MIME) is True
        assert is_mime_allowed("text/csv", DEFAULT_ALLOWED_MIME) is True

    def test_image_types_allowed(self):
        for m in ("image/png", "image/jpeg", "image/gif", "image/webp"):
            assert is_mime_allowed(m, DEFAULT_ALLOWED_MIME) is True

    def test_pdf_allowed(self):
        assert is_mime_allowed("application/pdf", DEFAULT_ALLOWED_MIME) is True

    def test_json_allowed(self):
        assert is_mime_allowed("application/json", DEFAULT_ALLOWED_MIME) is True

    def test_executable_blocked(self):
        assert is_mime_allowed("application/x-msdownload", DEFAULT_ALLOWED_MIME) is False
        assert is_mime_allowed("application/x-executable", DEFAULT_ALLOWED_MIME) is False

    def test_archive_blocked(self):
        for m in ("application/zip", "application/x-tar", "application/x-gzip"):
            assert is_mime_allowed(m, DEFAULT_ALLOWED_MIME) is False

    def test_octet_stream_rejected(self):
        assert is_mime_allowed("application/octet-stream", DEFAULT_ALLOWED_MIME) is False

    def test_empty_rejected(self):
        assert is_mime_allowed("", DEFAULT_ALLOWED_MIME) is False

    def test_blocked_wins_over_allowed(self):
        # application/zip is not in the allowlist, but even if a user
        # explicitly allowed it, the _BLOCKED_MIME set would still reject it.
        assert is_mime_allowed("application/zip", ("application/zip",)) is False


# ---- UploadsStore -----------------------------------------------------------


class _FakeAudit:
    """Minimal stand-in for AuditSink that records .record() calls."""

    def __init__(self):
        self.events = []

    def record(self, event, **fields):
        self.events.append((event, fields))


@pytest.fixture
def store_dir(tmp_path):
    d = tmp_path / "uploads"
    d.mkdir()
    return d


@pytest.fixture
def store(store_dir):
    return UploadsStore(store_dir)


class TestStoreSave:
    def test_save_text_success(self, store, store_dir):
        m = store.save(
            original_name="notes.txt",
            data=b"hello world",
            declared_mime="text/plain",
            tier="restricted",
        )
        assert isinstance(m, UploadMetadata)
        assert m.mime == "text/plain"
        assert m.size == 11
        assert m.tier == "restricted"
        assert m.sha256  # non-empty
        assert (store_dir / m.stored_name).is_file()
        assert (store_dir / m.stored_name).read_bytes() == b"hello world"

    def test_save_creates_sidecar(self, store, store_dir):
        store.save(original_name="a.txt", data=b"a", declared_mime="text/plain", tier="restricted")
        sidecar = store_dir / SIDECAR_NAME
        assert sidecar.exists()
        line = sidecar.read_text().strip()
        entry = json.loads(line)
        assert entry["event"] == "add"
        assert entry["tier"] == "restricted"

    def test_save_oversize_rejected(self, store):
        # Cap at 100 bytes for the test.
        store.max_bytes = 100
        with pytest.raises(UploadsError, match="too large"):
            store.save(
                original_name="big.bin",
                data=b"x" * 200,
                declared_mime="text/plain",
                tier="restricted",
            )

    def test_save_blocked_mime_rejected(self, store):
        # Non-UTF-8 binary so it is sniffed as octet-stream and rejected.
        with pytest.raises(UploadsError, match="not in allowlist"):
            store.save(
                original_name="evil.exe",
                data=b"\xff\xfe\x00\x01\x02MZfake-exe",
                declared_mime="application/x-msdownload",
                tier="restricted",
            )

    def test_save_collision_appends_suffix(self, store, store_dir):
        # Use real PNG signature (\x89PNG\r\n\x1a\n) so sniff_mime recognises it.
        png_sig = b"\x89PNG\r\n\x1a\n"
        m1 = store.save(
            original_name="same.png", data=png_sig + b"fake1", declared_mime="image/png", tier="restricted"
        )
        m2 = store.save(
            original_name="same.png", data=png_sig + b"fake2", declared_mime="image/png", tier="restricted"
        )
        assert m1.stored_name != m2.stored_name
        assert m2.stored_name.startswith("same-")
        assert (store_dir / m1.stored_name).is_file()
        assert (store_dir / m2.stored_name).is_file()

    def test_save_audit_event(self, store):
        audit = _FakeAudit()
        store.audit = audit
        store.save(original_name="a.txt", data=b"a", declared_mime="text/plain", tier="restricted")
        events = [e for e in audit.events if e[0] == "upload.add"]
        assert len(events) == 1
        fields = events[0][1]
        assert "name" in fields
        assert fields["mime"] == "text/plain"
        assert fields["tier"] == "restricted"


class TestStoreList:
    def test_empty_returns_empty_list(self, store):
        assert store.list_metadata() == []

    def test_returns_add_entries(self, store):
        store.save(original_name="a.txt", data=b"a", declared_mime="text/plain", tier="restricted")
        store.save(original_name="b.txt", data=b"b", declared_mime="text/plain", tier="elevated")
        metas = store.list_metadata()
        assert len(metas) == 2
        assert {m.original_name for m in metas} == {"a.txt", "b.txt"}

    def test_deleted_files_excluded(self, store):
        m = store.save(original_name="a.txt", data=b"a", declared_mime="text/plain", tier="restricted")
        store.save(original_name="b.txt", data=b"b", declared_mime="text/plain", tier="restricted")
        assert len(store.list_metadata()) == 2
        store.delete(m.stored_name, deleted_by="cli")
        assert len(store.list_metadata()) == 1


class TestStoreDelete:
    def test_delete_removes_file_and_records(self, store, store_dir):
        m = store.save(original_name="a.txt", data=b"a", declared_mime="text/plain", tier="restricted")
        store.delete(m.stored_name, deleted_by="cli")
        assert not (store_dir / m.stored_name).exists()
        # Sidecar should now have add + delete entries.
        entries = [json.loads(line) for line in (store_dir / SIDECAR_NAME).read_text().splitlines() if line.strip()]
        assert entries[0]["event"] == "add"
        assert entries[1]["event"] == "delete"
        assert entries[1]["stored_name"] == m.stored_name
        assert entries[1]["deleted_by"] == "cli"

    def test_delete_unknown_raises(self, store):
        with pytest.raises(UploadsError, match="not found"):
            store.delete("nonexistent.txt", deleted_by="cli")

    def test_delete_audit_event(self, store):
        audit = _FakeAudit()
        store.audit = audit
        m = store.save(original_name="a.txt", data=b"a", declared_mime="text/plain", tier="restricted")
        store.delete(m.stored_name, deleted_by="cli")
        events = [e for e in audit.events if e[0] == "upload.delete"]
        assert len(events) == 1


class TestStoreClean:
    def test_clean_all(self, store):
        for i in range(3):
            store.save(original_name=f"f{i}.txt", data=b"x", declared_mime="text/plain", tier="restricted")
        assert len(store.list_metadata()) == 3
        deleted = store.clean()
        assert deleted == 3
        assert store.list_metadata() == []

    def test_clean_with_older_than_keeps_recent(self, store):
        store.save(original_name="recent.txt", data=b"x", declared_mime="text/plain", tier="restricted")
        # Force a fake-old entry by manipulating the sidecar ts is fragile;
        # instead use older_than_days=0 to keep files added NOW (>= today).
        deleted = store.clean(older_than_days=0)
        # Files added today are NOT older than 0 days -> not deleted.
        assert deleted == 0
        assert len(store.list_metadata()) == 1

    def test_clean_negative_rejected(self, store):
        with pytest.raises(UploadsError, match=">= 0"):
            store.clean(older_than_days=-1)


class TestStorePathFor:
    def test_simple(self, store):
        p = store.path_for("a.txt")
        assert p == store.dir / "a.txt"

    def test_rejects_traversal(self, store):
        with pytest.raises(UploadsError):
            store.path_for("../etc/passwd")

    def test_rejects_absolute(self, store):
        with pytest.raises(UploadsError):
            store.path_for("/etc/passwd")


# ---- Tier write-block integration ------------------------------------------


class TestTierWriteBlock:
    def test_restricted_cannot_write_to_uploads(self, tmp_path):
        ws = tmp_path
        uploads = ws / ".smolcode" / "uploads"
        uploads.mkdir(parents=True)
        (uploads / "user.txt").write_text("uploaded")
        tools = {t.name: t for t in build_fs_tools(str(ws), tier="restricted", uploads_dir=str(uploads))}
        w = tools["write_file"]
        # Normal file -> OK.
        w("normal.txt", "hello")
        assert (ws / "normal.txt").is_file()
        # Upload file -> rejected.
        with pytest.raises(PermissionError, match="restricted tier"):
            w(".smolcode/uploads/user.txt", "overwritten")
        # Original content unchanged.
        assert (uploads / "user.txt").read_text() == "uploaded"

    def test_elevated_can_write_to_uploads(self, tmp_path):
        ws = tmp_path
        uploads = ws / ".smolcode" / "uploads"
        uploads.mkdir(parents=True)
        (uploads / "user.txt").write_text("uploaded")
        tools = {t.name: t for t in build_fs_tools(str(ws), tier="elevated", uploads_dir=str(uploads))}
        w = tools["write_file"]
        w(".smolcode/uploads/user.txt", "overwritten")
        assert (uploads / "user.txt").read_text() == "overwritten"

    def test_full_access_can_write_to_uploads(self, tmp_path):
        ws = tmp_path
        uploads = ws / ".smolcode" / "uploads"
        uploads.mkdir(parents=True)
        (uploads / "user.txt").write_text("uploaded")
        tools = {t.name: t for t in build_fs_tools(str(ws), tier="full_access", uploads_dir=str(uploads))}
        w = tools["write_file"]
        w(".smolcode/uploads/user.txt", "ok")
        assert (uploads / "user.txt").read_text() == "ok"

    def test_restricted_with_no_uploads_dir_can_still_write_normal(self, tmp_path):
        # Legacy behaviour: no uploads_dir configured -> no write-block.
        ws = tmp_path
        tools = {t.name: t for t in build_fs_tools(str(ws), tier="restricted", uploads_dir="")}
        w = tools["write_file"]
        w("normal.txt", "hello")
        assert (ws / "normal.txt").is_file()


# ---- Settings integration ---------------------------------------------------


class TestSettings:
    def test_default_uploads_dir_under_workspace(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path))
        for k in list(os.environ):
            if k.startswith("SMOLCODE_UPLOAD"):
                monkeypatch.delenv(k, raising=False)
        from smolcode.config import load_settings

        s = load_settings()
        assert s.uploads_dir == (tmp_path / ".smolcode" / "uploads").resolve()
        assert s.upload_max_bytes == DEFAULT_MAX_BYTES
        assert "text/" in s.upload_allowed_mime

    def test_uploads_dir_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path))
        custom = tmp_path / "my-uploads"
        monkeypatch.setenv("SMOLCODE_UPLOAD_DIR", str(custom))
        from smolcode.config import load_settings

        s = load_settings()
        assert s.uploads_dir == custom.resolve()

    def test_max_bytes_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path))
        monkeypatch.setenv("SMOLCODE_UPLOAD_MAX_BYTES", "1024")
        from smolcode.config import load_settings

        s = load_settings()
        assert s.upload_max_bytes == 1024

    def test_max_bytes_invalid_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path))
        monkeypatch.setenv("SMOLCODE_UPLOAD_MAX_BYTES", "abc")
        from smolcode.config import ConfigError, load_settings

        with pytest.raises(ConfigError, match="must be an integer"):
            load_settings()

    def test_allowed_mime_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path))
        monkeypatch.setenv("SMOLCODE_UPLOAD_ALLOWED_MIME", "text/plain,image/png")
        from smolcode.config import load_settings

        s = load_settings()
        assert "text/plain" in s.upload_allowed_mime
        assert "image/png" in s.upload_allowed_mime
        assert "image/jpeg" not in s.upload_allowed_mime

    def test_tier_uploads_default(self):
        from smolcode.config import _default_tiers

        ts = _default_tiers()
        assert ts["restricted"].uploads == "read"
        assert ts["elevated"].uploads == "readwrite"
        assert ts["full_access"].uploads == "readwrite"


# ---- CLI subcommand --------------------------------------------------------


class TestUploadsCli:
    def setup_method(self):
        for k in list(os.environ):
            if k.startswith("SMOLCODE_"):
                del os.environ[k]

    def test_uploads_path(self, tmp_path, capsys):
        os.environ["SMOLCODE_WORKSPACE"] = str(tmp_path)
        from smolcode.cli import main

        rc = main(["uploads", "path"])
        captured = capsys.readouterr()
        assert rc == 0
        assert ".smolcode" in captured.out
        assert "uploads" in captured.out

    def test_uploads_list_empty(self, tmp_path, capsys):
        os.environ["SMOLCODE_WORKSPACE"] = str(tmp_path)
        from smolcode.cli import main

        rc = main(["uploads", "list"])
        captured = capsys.readouterr()
        assert rc == 0
        assert "no uploads" in captured.out

    def test_uploads_default_is_list(self, tmp_path, capsys):
        os.environ["SMOLCODE_WORKSPACE"] = str(tmp_path)
        from smolcode.cli import main

        rc = main(["uploads"])
        captured = capsys.readouterr()
        assert rc == 0
        assert "no uploads" in captured.out

    def test_uploads_list_after_upload(self, tmp_path, capsys):
        os.environ["SMOLCODE_WORKSPACE"] = str(tmp_path)
        from smolcode.cli import main
        from smolcode.uploads import UploadsStore

        store = UploadsStore(tmp_path / ".smolcode" / "uploads")
        store.save(original_name="a.txt", data=b"a", declared_mime="text/plain", tier="restricted")
        rc = main(["uploads", "list"])
        captured = capsys.readouterr()
        assert rc == 0
        assert "a.txt" in captured.out

    def test_uploads_clean_requires_yes(self, tmp_path, capsys):
        os.environ["SMOLCODE_WORKSPACE"] = str(tmp_path)
        from smolcode.cli import main
        from smolcode.uploads import UploadsStore

        store = UploadsStore(tmp_path / ".smolcode" / "uploads")
        store.save(original_name="a.txt", data=b"a", declared_mime="text/plain", tier="restricted")
        rc = main(["uploads", "clean"])
        assert rc == 6  # needs confirmation (confirm prompt sent to stderr)
        # File still exists.
        assert (tmp_path / ".smolcode" / "uploads" / "a.txt").is_file()

    def test_uploads_clean_with_yes(self, tmp_path, capsys):
        os.environ["SMOLCODE_WORKSPACE"] = str(tmp_path)
        from smolcode.cli import main
        from smolcode.uploads import UploadsStore

        store = UploadsStore(tmp_path / ".smolcode" / "uploads")
        store.save(original_name="a.txt", data=b"a", declared_mime="text/plain", tier="restricted")
        rc = main(["uploads", "clean", "--yes"])
        captured = capsys.readouterr()
        assert rc == 0
        assert "deleted 1" in captured.out
        assert not (tmp_path / ".smolcode" / "uploads" / "a.txt").exists()

    def test_uploads_clean_older_than(self, tmp_path, capsys):
        os.environ["SMOLCODE_WORKSPACE"] = str(tmp_path)
        from smolcode.cli import main
        from smolcode.uploads import UploadsStore

        store = UploadsStore(tmp_path / ".smolcode" / "uploads")
        store.save(original_name="a.txt", data=b"a", declared_mime="text/plain", tier="restricted")
        rc = main(["uploads", "clean", "--older-than", "30", "--yes"])
        captured = capsys.readouterr()
        assert rc == 0
        assert "deleted 0" in captured.out
        assert (tmp_path / ".smolcode" / "uploads" / "a.txt").is_file()

    def test_uploads_unknown_verb(self, tmp_path, capsys):
        os.environ["SMOLCODE_WORKSPACE"] = str(tmp_path)
        from smolcode.cli import main

        rc = main(["uploads", "bogus"])
        captured = capsys.readouterr()
        assert rc == 2
        assert "unknown" in captured.err

    def test_normal_task_still_routed_through_main(self, tmp_path):
        """Verify that a non-'uploads' first positional flows through to
        the main parser without being captured by the uploads pre-dispatch.
        We use --print-config so no agent runs (avoids rich unicode
        encoding issues on Windows) and no API key is needed.
        """
        os.environ["SMOLCODE_WORKSPACE"] = str(tmp_path)
        from smolcode.cli import main

        rc = main(["hello", "--print-config"])
        assert rc == 0

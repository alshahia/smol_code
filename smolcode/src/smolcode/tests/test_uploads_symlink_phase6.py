"""Phase 6 section 6.4 (R11 / H4) -- uploads symlink hardening.

Bug surface: every path in UploadsStore was resolved with pathlib and
then used through methods that FOLLOW symlinks -- Path.read_bytes,
Path.write_bytes, Path.unlink, Path.is_file, Path.exists.

path_for() rejects a stored_name containing a separator, so the name
itself cannot traverse. It does nothing about the filesystem entry that
name points at. Anyone able to create one entry in the uploads directory
-- which includes model-written code under the rw workspace bind mount --
could plant a symlink and get an arbitrary-file primitive:

    read   -> exfiltrate any file the server process can open
    delete -> unlink any file the server process can remove
    save   -> with allow_overwrite, write through the link

The tests use symlinks so they run on any platform CI covers, and skip
where the OS refuses to create one (Windows without the required
privilege). They need no Docker daemon.
"""

from __future__ import annotations

import os

import pytest

from smolcode.uploads import UploadsError, UploadsStore


def _make_store(tmp_path, **kw):
    d = tmp_path / "uploads"
    d.mkdir()
    return UploadsStore(d, **kw)


def _link_supported(tmp_path) -> bool:
    """Can this platform create a symlink here? Returns False rather than
    erroring, so the suite degrades to skips instead of false passes."""
    probe = tmp_path / "_probe_target"
    link = tmp_path / "_probe_link"
    probe.write_text("x", encoding="utf-8")
    try:
        os.symlink(probe, link)
    except (OSError, NotImplementedError, AttributeError):
        return False
    return link.is_symlink()


needs_symlink = pytest.mark.skipif(not _link_supported, reason="platform cannot create symlinks")


class TestReadRejectsSymlink:
    def test_read_refuses_a_symlink_pointing_outside_the_store(self, tmp_path):
        if not _link_supported(tmp_path):
            pytest.skip("platform cannot create symlinks")
        secret = tmp_path / "secret.txt"
        secret.write_text("TOP-SECRET-VALUE", encoding="utf-8")
        store = _make_store(tmp_path)
        os.symlink(secret, store.dir / "innocent.txt")

        with pytest.raises(UploadsError):
            store.read("innocent.txt")

    def test_the_secret_is_not_disclosed_in_the_error(self, tmp_path):
        if not _link_supported(tmp_path):
            pytest.skip("platform cannot create symlinks")
        secret = tmp_path / "secret.txt"
        secret.write_text("TOP-SECRET-VALUE", encoding="utf-8")
        store = _make_store(tmp_path)
        os.symlink(secret, store.dir / "innocent.txt")

        with pytest.raises(UploadsError) as exc:
            store.read("innocent.txt")
        assert "TOP-SECRET-VALUE" not in str(exc.value)

    def test_a_regular_file_still_reads(self, tmp_path):
        store = _make_store(tmp_path)
        meta = store.save(original_name="a.txt", data=b"hello", tier="restricted")
        assert store.read(meta.stored_name) == b"hello"


class TestDeleteRejectsSymlink:
    def test_delete_refuses_to_unlink_the_symlink_target(self, tmp_path):
        if not _link_supported(tmp_path):
            pytest.skip("platform cannot create symlinks")
        victim = tmp_path / "important.txt"
        victim.write_text("do not delete me", encoding="utf-8")
        store = _make_store(tmp_path)
        link = store.dir / "boring.txt"
        os.symlink(victim, link)

        with pytest.raises(UploadsError):
            store.delete("boring.txt")

        # The whole point: the target is still on disk.
        assert victim.exists()
        assert victim.read_text(encoding="utf-8") == "do not delete me"


class TestListMetadataSkipsSymlinks:
    def test_a_symlinked_entry_is_not_listed(self, tmp_path):
        if not _link_supported(tmp_path):
            pytest.skip("platform cannot create symlinks")
        secret = tmp_path / "secret.txt"
        secret.write_text("TOP-SECRET-VALUE", encoding="utf-8")
        store = _make_store(tmp_path)
        real = store.save(original_name="real.txt", data=b"ok", tier="restricted")
        os.symlink(secret, store.dir / "fake.txt")
        # The sidecar entry is what makes this a real test. Without it the
        # listing skips fake.txt simply because nothing ever recorded it,
        # which would pass for the wrong reason.
        store._append_sidecar(
            {
                "event": "add",
                "ts": "2026-09-24T00:00:00Z",
                "original_name": "fake.txt",
                "stored_name": "fake.txt",
                "size": 16,
                "mime": "text/plain",
                "sha256": "deadbeef",
                "tier": "restricted",
                "uploaded_by": "test",
            }
        )

        names = [m.stored_name for m in store.list_metadata()]
        assert real.stored_name in names
        assert "fake.txt" not in names


class TestSaveRefusesSymlinkTarget:
    def test_save_with_overwrite_does_not_write_through_a_link(self, tmp_path):
        if not _link_supported(tmp_path):
            pytest.skip("platform cannot create symlinks")
        victim = tmp_path / "config.py"
        victim.write_text("ORIGINAL", encoding="utf-8")
        store = _make_store(tmp_path, allow_overwrite=True)
        os.symlink(victim, store.dir / "payload.txt")

        with pytest.raises(UploadsError):
            store.save(original_name="payload.txt", data=b"OVERWRITTEN", tier="restricted")

        assert victim.read_text(encoding="utf-8") == "ORIGINAL"

    def test_save_onto_a_plain_file_with_overwrite_still_works(self, tmp_path):
        store = _make_store(tmp_path, allow_overwrite=True)
        first = store.save(original_name="a.txt", data=b"one", tier="restricted")
        second = store.save(original_name="a.txt", data=b"two", tier="restricted")
        assert first.stored_name == second.stored_name
        assert store.read(second.stored_name) == b"two"


class TestDirectorySymlink:
    def test_a_symlink_to_a_directory_is_not_followed(self, tmp_path):
        if not _link_supported(tmp_path):
            pytest.skip("platform cannot create symlinks")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "target.txt").write_text("secret", encoding="utf-8")
        store = _make_store(tmp_path)
        os.symlink(elsewhere, store.dir / "dirlink")

        with pytest.raises(UploadsError):
            store.read("dirlink/target.txt")


class TestCleanIsAlsoSafe:
    def test_clean_does_not_delete_through_a_symlink(self, tmp_path):
        if not _link_supported(tmp_path):
            pytest.skip("platform cannot create symlinks")
        victim = tmp_path / "old.txt"
        victim.write_text("keep", encoding="utf-8")
        store = _make_store(tmp_path)
        os.symlink(victim, store.dir / "aged.txt")
        store._append_sidecar(
            {
                "event": "add",
                "ts": "1970-01-01T00:00:00Z",
                "original_name": "aged.txt",
                "stored_name": "aged.txt",
                "size": 4,
                "mime": "text/plain",
                "sha256": "x",
                "tier": "restricted",
                "uploaded_by": "test",
            }
        )

        store.clean(older_than_days=1)
        assert victim.exists()

"""M4 - AuditSink tests (per docs/roadmap.md 6: AuditSink rejects 'w' mode)."""

import json
import os
import threading

import pytest

from smolcode.audit import AuditError, AuditSink, default_audit_path


# ---- Mode enforcement (per roadmap 6 M4 acceptance gate) -----------------


class TestModeEnforcement:
    def test_append_mode_accepted(self, tmp_path):
        path = tmp_path / "a.jsonl"
        AuditSink(path)
        assert path.exists()

    def test_append_plus_mode_accepted(self, tmp_path):
        path = tmp_path / "aplus.jsonl"
        AuditSink(path, mode="a+")
        assert path.exists()

    def test_write_mode_rejected(self, tmp_path):
        path = tmp_path / "w.jsonl"
        with pytest.raises(AuditError):
            AuditSink(path, mode="w")
        assert not path.exists()

    def test_write_text_mode_rejected(self, tmp_path):
        path = tmp_path / "wt.jsonl"
        with pytest.raises(AuditError):
            AuditSink(path, mode="wt")
        assert not path.exists()

    def test_exclusive_mode_rejected(self, tmp_path):
        path = tmp_path / "x.jsonl"
        with pytest.raises(AuditError):
            AuditSink(path, mode="x")
        assert not path.exists()

    def test_read_mode_rejected(self, tmp_path):
        path = tmp_path / "r.jsonl"
        with pytest.raises(AuditError):
            AuditSink(path, mode="r")
        assert not path.exists()

    def test_mode_error_message_mentions_append(self, tmp_path):
        path = tmp_path / "w.jsonl"
        with pytest.raises(AuditError) as ei:
            AuditSink(path, mode="w")
        assert "append" in str(ei.value).lower()


# ---- Append-only guarantee ------------------------------------------------


class TestAppendOnly:
    def test_does_not_truncate_existing_log(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        path.write_text('{"ts":"2020-01-01T00:00:00Z","event":"start"}\n', encoding="utf-8")
        before = path.read_text(encoding="utf-8")
        sink = AuditSink(path)
        sink.record("end", exit_code=0)
        sink.close()
        after = path.read_text(encoding="utf-8")
        # Prior content is preserved; new line appended at the end.
        assert before in after
        assert after.count("\n") == 2

    def test_two_sinks_append_to_same_file(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        s1 = AuditSink(path)
        s1.record("start")
        s1.close()
        s2 = AuditSink(path)
        s2.record("end")
        s2.close()
        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        assert [line["event"] for line in lines] == ["start", "end"]


# ---- Valid JSONL output ---------------------------------------------------


class TestJSONLOutput:
    def test_record_writes_one_valid_json_line(self, tmp_path):
        path = tmp_path / "a.jsonl"
        sink = AuditSink(path)
        sink.record("start", tier="restricted", task="hi")
        sink.close()
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
        assert len(lines) == 1
        obj = json.loads(lines[0])
        assert obj["event"] == "start"
        assert obj["tier"] == "restricted"
        assert obj["task"] == "hi"
        assert "ts" in obj
        assert "pid" in obj

    def test_each_record_is_a_separate_line(self, tmp_path):
        path = tmp_path / "a.jsonl"
        sink = AuditSink(path)
        for i in range(5):
            sink.record("step", step=i)
        sink.close()
        text = path.read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if line]
        assert len(lines) == 5
        for line in lines:
            obj = json.loads(line)
            assert "event" in obj

    def test_start_end_error_have_canonical_keys(self, tmp_path):
        path = tmp_path / "a.jsonl"
        sink = AuditSink(path)
        sink.start(
            tier="full_access",
            task="x",
            model="m",
            provider="p",
            executor="docker",
            workspace="/w",
        )
        sink.step(1, "act")
        try:
            raise ValueError("boom")
        except ValueError as e:
            sink.error(e)
        sink.end(exit_code=1, duration_s=0.5)
        sink.close()
        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        assert [line["event"] for line in lines] == ["start", "step", "error", "end"]
        assert lines[0]["tier"] == "full_access"
        assert lines[2]["kind"] == "ValueError"
        assert lines[2]["message"] == "boom"
        assert lines[3]["exit_code"] == 1
        assert isinstance(lines[3]["duration_s"], float)


# ---- Lifecycle ------------------------------------------------------------


class TestLifecycle:
    def test_close_is_idempotent(self, tmp_path):
        path = tmp_path / "a.jsonl"
        sink = AuditSink(path)
        sink.record("start")
        sink.close()
        sink.close()  # must not raise

    def test_record_after_close_raises(self, tmp_path):
        path = tmp_path / "a.jsonl"
        sink = AuditSink(path)
        sink.close()
        with pytest.raises(AuditError):
            sink.record("start")

    def test_context_manager_closes(self, tmp_path):
        path = tmp_path / "a.jsonl"
        with AuditSink(path) as sink:
            sink.record("start")
        # After exit, writing must raise.
        with pytest.raises(AuditError):
            sink.record("after")

    def test_creates_parent_dir(self, tmp_path):
        path = tmp_path / "deep" / "logs" / "audit.jsonl"
        sink = AuditSink(path)
        sink.record("start")
        sink.close()
        assert path.exists()


# ---- default_audit_path --------------------------------------------------


class TestDefaultAuditPath:
    def test_default_uses_logs_under_cwd(self, monkeypatch):
        monkeypatch.delenv("SMOLCODE_AUDIT_LOG", raising=False)
        p = default_audit_path()
        assert p.endswith(os.path.join("logs", "audit.jsonl"))

    def test_env_var_overrides(self, monkeypatch, tmp_path):
        override = str(tmp_path / "custom.jsonl")
        monkeypatch.setenv("SMOLCODE_AUDIT_LOG", override)
        assert default_audit_path() == override


# ---- Thread safety --------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_writes_produce_valid_jsonl(self, tmp_path):
        path = tmp_path / "a.jsonl"
        sink = AuditSink(path)

        def worker(i):
            for j in range(20):
                sink.record("step", step=i * 100 + j)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        sink.close()

        text = path.read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if line]
        assert len(lines) == 100
        for line in lines:
            obj = json.loads(line)  # must parse
            assert obj["event"] == "step"


# ---- M13.1: hash chain (tamper evidence) -------------------------------


class TestHashChain:
    def test_hash_chain_enabled_by_default(self, tmp_path, monkeypatch):
        """By default (no env override), each line carries prev_hash + entry_hash."""
        monkeypatch.delenv("SMOLCODE_AUDIT_HASH_CHAIN", raising=False)
        path = tmp_path / "a.jsonl"
        sink = AuditSink(path)
        sink.record("start")
        sink.close()
        line = path.read_text(encoding="utf-8").strip()
        obj = json.loads(line)
        assert "prev_hash" in obj
        assert "entry_hash" in obj
        # Genesis prev_hash is 64 zero hex chars.
        assert obj["prev_hash"] == "0" * 64
        # entry_hash is 64 lowercase hex chars.
        assert len(obj["entry_hash"]) == 64
        assert all(c in "0123456789abcdef" for c in obj["entry_hash"])

    def test_hash_chain_links_entries(self, tmp_path, monkeypatch):
        """Line 2's prev_hash must equal line 1's entry_hash."""
        monkeypatch.delenv("SMOLCODE_AUDIT_HASH_CHAIN", raising=False)
        path = tmp_path / "a.jsonl"
        sink = AuditSink(path)
        sink.record("step", step=1)
        sink.record("step", step=2)
        sink.record("step", step=3)
        sink.close()
        lines = [json.loads(line_) for line_ in path.read_text(encoding="utf-8").splitlines() if line_]
        assert len(lines) == 3
        assert lines[0]["prev_hash"] == "0" * 64
        assert lines[1]["prev_hash"] == lines[0]["entry_hash"]
        assert lines[2]["prev_hash"] == lines[1]["entry_hash"]

    def test_hash_chain_opt_out_via_env(self, tmp_path, monkeypatch):
        """SMOLCODE_AUDIT_HASH_CHAIN=1 disables chain fields on write."""
        monkeypatch.setenv("SMOLCODE_AUDIT_HASH_CHAIN", "1")
        path = tmp_path / "a.jsonl"
        sink = AuditSink(path)
        sink.record("start")
        sink.close()
        obj = json.loads(path.read_text(encoding="utf-8").strip())
        assert "prev_hash" not in obj
        assert "entry_hash" not in obj

    def test_hash_chain_explicit_kwarg_overrides_env(self, tmp_path, monkeypatch):
        """Explicit hash_chain=False kwarg beats the env var."""
        monkeypatch.setenv("SMOLCODE_AUDIT_HASH_CHAIN", "0")  # would enable
        path = tmp_path / "a.jsonl"
        sink = AuditSink(path, hash_chain=False)
        sink.record("start")
        sink.close()
        obj = json.loads(path.read_text(encoding="utf-8").strip())
        assert "prev_hash" not in obj

    def test_hash_chain_does_not_pollute_recompute(self, tmp_path, monkeypatch):
        """entry_hash must be computed WITHOUT the hash fields themselves."""
        monkeypatch.delenv("SMOLCODE_AUDIT_HASH_CHAIN", raising=False)
        path = tmp_path / "a.jsonl"
        sink = AuditSink(path)
        sink.record("start", tier="restricted", task="x")
        sink.close()
        obj = json.loads(path.read_text(encoding="utf-8").strip())
        # Re-compute the hash from the line's own prev_hash + payload
        # excluding the hash fields. Must match the recorded entry_hash.
        from smolcode.audit import _compute_entry_hash

        recomputed = _compute_entry_hash(obj["prev_hash"], dict(obj))
        assert recomputed == obj["entry_hash"]


class TestVerifyChain:
    def test_verify_clean_log_returns_ok(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SMOLCODE_AUDIT_HASH_CHAIN", raising=False)
        path = tmp_path / "a.jsonl"
        sink = AuditSink(path)
        sink.record("start")
        sink.record("end")
        sink.close()
        from smolcode.audit import verify_chain

        r = verify_chain(path)
        assert r.ok is True
        assert r.entries == 2
        assert r.chained_entries == 2
        assert r.bad_line is None
        assert r.first_unverifiable_line is None

    def test_verify_detects_tampered_line(self, tmp_path, monkeypatch):
        """Modify one byte in the payload; verify must report bad_line=N."""
        monkeypatch.delenv("SMOLCODE_AUDIT_HASH_CHAIN", raising=False)
        path = tmp_path / "a.jsonl"
        sink = AuditSink(path)
        sink.record("start", tier="restricted")
        sink.record("step", step=1)
        sink.record("end")
        sink.close()
        # Tamper with line 2 (the "step" entry): change "step" to "STEP".
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        # Reconstruct line 2 with the modification (single byte difference
        # that does NOT touch the chain fields directly).
        obj = json.loads(lines[1])
        obj["event"] = "STEP"  # tampered content
        lines[1] = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        from smolcode.audit import verify_chain

        r = verify_chain(path)
        assert r.ok is False
        assert r.bad_line == 2
        assert r.chained_entries == 1  # only line 1 verified

    def test_verify_detects_broken_chain_link(self, tmp_path, monkeypatch):
        """Replacing a line's entry_hash with a wrong value breaks the chain."""
        monkeypatch.delenv("SMOLCODE_AUDIT_HASH_CHAIN", raising=False)
        path = tmp_path / "a.jsonl"
        sink = AuditSink(path)
        sink.record("a")
        sink.record("b")
        sink.record("c")
        sink.close()
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        obj = json.loads(lines[1])
        # Keep payload + prev_hash the same; mutate entry_hash.
        obj["entry_hash"] = "f" * 64
        lines[1] = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        from smolcode.audit import verify_chain

        r = verify_chain(path)
        assert r.ok is False
        assert r.bad_line == 2

    def test_verify_pre_m13_log_reports_unverifiable_not_failure(self, tmp_path):
        """Logs without chain fields are reported as first_unverifiable_line."""
        path = tmp_path / "old.jsonl"
        # Write a fake pre-M13 log (no chain fields).
        path.write_text(
            '{"ts":"2020-01-01T00:00:00Z","event":"start","tier":"restricted"}\n',
            encoding="utf-8",
        )
        from smolcode.audit import verify_chain

        r = verify_chain(path)
        assert r.ok is False  # cannot call a non-chained log OK
        assert r.bad_line is None
        assert r.first_unverifiable_line == 1

    def test_verify_empty_log(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        from smolcode.audit import verify_chain

        r = verify_chain(path)
        assert r.ok is True
        assert r.entries == 0
        assert r.chained_entries == 0

    def test_verify_missing_file_raises(self, tmp_path):
        from smolcode.audit import verify_chain

        with pytest.raises(FileNotFoundError):
            verify_chain(tmp_path / "does_not_exist.jsonl")

    def test_verify_directory_raises_audit_error(self, tmp_path):
        from smolcode.audit import AuditError, verify_chain

        with pytest.raises(AuditError):
            verify_chain(tmp_path)


class TestComputeEntryHash:
    def test_compute_is_deterministic(self):
        from smolcode.audit import _compute_entry_hash

        payload = {"event": "start", "ts": "2020-01-01T00:00:00Z", "pid": 1, "tier": "restricted"}
        prev = "0" * 64
        h1 = _compute_entry_hash(prev, payload)
        h2 = _compute_entry_hash(prev, payload)
        assert h1 == h2
        assert len(h1) == 64

    def test_compute_excludes_hash_fields(self):
        """Including prev_hash/entry_hash in the payload must not change the hash."""
        from smolcode.audit import _compute_entry_hash

        prev = "0" * 64
        a = {"event": "x"}
        b = {"event": "x", "prev_hash": "abc", "entry_hash": "def"}
        assert _compute_entry_hash(prev, a) == _compute_entry_hash(prev, b)

    def test_compute_changes_when_payload_changes(self):
        from smolcode.audit import _compute_entry_hash

        prev = "0" * 64
        a = {"event": "x", "n": 1}
        b = {"event": "x", "n": 2}
        assert _compute_entry_hash(prev, a) != _compute_entry_hash(prev, b)

    def test_compute_changes_when_prev_changes(self):
        from smolcode.audit import _compute_entry_hash

        payload = {"event": "x"}
        a = _compute_entry_hash("0" * 64, payload)
        b = _compute_entry_hash("a" * 64, payload)
        assert a != b


class TestRotate:
    """Tests for rotate_audit_log() (M14.3, decision 0018)."""

    def _make_sink(self, tmp_path, entries):
        from smolcode.audit import AuditSink

        log = tmp_path / "audit.jsonl"
        s = AuditSink(log)
        for e in entries:
            s.record(**e)
        s.close()
        return log

    def _seed(self, tmp_path, n=3):
        return self._make_sink(
            tmp_path,
            [
                {"event": "start", "tier": "restricted", "task": "rotate-test"},
                {"event": "step", "step": 1, "action": "final_answer"},
                {"event": "end", "exit_code": 0, "duration_s": 0.1},
            ][:n],
        )

    def test_clean_log_rotates_and_gzips(self, tmp_path):
        """Clean log rotates, gz, and new live log is empty."""
        from pathlib import Path

        from smolcode.audit import rotate_audit_log

        log = self._seed(tmp_path)
        assert log.exists() and log.stat().st_size > 0
        result = rotate_audit_log(log, stamp="20260823")
        assert result.chain_ok is True
        assert result.rotated_to is not None
        # The .gz file exists and contains the original entries.
        gz = Path(result.rotated_to)
        assert gz.exists()
        assert gz.suffix == ".gz"
        # Live log no longer exists at the original path; the caller is
        # responsible for creating a fresh one on next write.
        assert not log.exists()
        # Sanity: decompressing returns the original payload.
        import gzip

        with gzip.open(gz, "rt", encoding="utf-8") as fp:
            lines = [ln for ln in fp.read().splitlines() if ln]
        assert len(lines) == 3

    def test_broken_chain_refuses(self, tmp_path):
        """Tampered log -> chain_ok=False, no files moved."""
        from smolcode.audit import rotate_audit_log

        log = self._seed(tmp_path)
        # Tamper with the first JSONL line: rewrite the 'task' field.
        raw = log.read_text(encoding="utf-8")
        first, _, rest = raw.partition("\n")
        import json as _json

        obj = _json.loads(first)
        obj["task"] = "tampered"
        tampered = _json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        log.write_text(tampered + "\n" + rest, encoding="utf-8")
        result = rotate_audit_log(log, stamp="20260823")
        assert result.chain_ok is False
        assert result.rotated_to is None
        assert "line" in result.chain_message
        # Live log was NOT moved.
        assert log.exists()

    def test_empty_log_is_noop(self, tmp_path):
        """Zero-byte log -> rotated_to is None, nothing archived."""
        from smolcode.audit import rotate_audit_log

        log = tmp_path / "audit.jsonl"
        log.write_text("", encoding="utf-8")
        result = rotate_audit_log(log, stamp="20260823")
        assert result.chain_ok is True
        assert result.rotated_to is None
        # The empty file is preserved (caller's AuditSink reopens it).
        assert log.exists()
        assert log.stat().st_size == 0

    def test_dry_run_does_not_move_files(self, tmp_path):
        """dry_run=True reports the plan but leaves files untouched."""
        from smolcode.audit import rotate_audit_log

        log = self._seed(tmp_path)
        size_before = log.stat().st_size
        result = rotate_audit_log(log, dry_run=True, stamp="20260823")
        assert result.dry_run is True
        assert result.chain_ok is True
        assert result.rotated_to is not None
        # Live log untouched.
        assert log.exists()
        assert log.stat().st_size == size_before
        # No .gz file was created.
        assert not (tmp_path / "audit-20260823.jsonl.gz").exists()

    def test_retention_sweep_deletes_old_archives(self, tmp_path):
        """Old .gz files (mtime > keep_days) are pruned."""
        import os
        import time

        from smolcode.audit import rotate_audit_log

        log = self._seed(tmp_path)
        # Seed two old archive files.
        old1 = tmp_path / "audit-20260101.jsonl.gz"
        old2 = tmp_path / "audit-20260201.jsonl.gz"
        old1.write_text("x", encoding="utf-8")
        old2.write_text("x", encoding="utf-8")
        # Backdate them to 100 days ago so keep_days=7 sweeps them.
        long_ago = time.time() - 100 * 86400
        os.utime(old1, (long_ago, long_ago))
        os.utime(old2, (long_ago, long_ago))
        result = rotate_audit_log(log, keep_days=7, stamp="20260823")
        assert not old1.exists()
        assert not old2.exists()
        assert len(result.deleted) == 2

    def test_collision_safe_stamping(self, tmp_path):
        """A pre-existing stamp gets a numeric suffix appended."""
        from smolcode.audit import rotate_audit_log

        log = self._seed(tmp_path)
        # Seed a file that already uses the stamp.
        pre = tmp_path / "audit-20260823.jsonl"
        pre.write_text("leftover", encoding="utf-8")
        result = rotate_audit_log(log, stamp="20260823")
        assert result.rotated_to is not None
        # The .gz must have a -1 suffix to avoid clobbering 'pre'.
        assert "audit-20260823-1.jsonl.gz" in result.rotated_to
        # And the leftover file is untouched.
        assert pre.exists()

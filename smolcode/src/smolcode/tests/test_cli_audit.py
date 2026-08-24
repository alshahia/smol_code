"""M13.2 - smolcode audit subcommand tests (decision 0016).

Covers:
  * `smolcode audit help` prints the usage block and exits 0.
  * `smolcode audit ls` reads the log and lists entries; missing log
    exits 3.
  * `smolcode audit grep <pattern>` filters by task/action/message;
    passes output through RedactSecretsFilter (so a leaked key in
    the log cannot be echoed to the terminal).
  * `smolcode audit verify` replays the hash chain; clean log -> 0,
    tampered log -> 1 with bad_line set, pre-M13 log -> 1 with
    first_unverifiable_line set.
  * unknown verbs + bad flags exit 2.
"""

from __future__ import annotations

import json

from smolcode.audit import AuditSink
from smolcode.cli import _audit_main


# ---- Helpers --------------------------------------------------------------


def _write_log(path, entries, hash_chain=True):
    """Write N entries into a JSONL audit log; default chained."""
    if hash_chain:
        s = AuditSink(path)
    else:
        s = AuditSink(path, hash_chain=False)
    for e in entries:
        s.record(**e)
    s.close()
    return path


def _read_log_lines(path):
    with open(path, "r", encoding="utf-8") as fp:
        return [line.rstrip("\r\n") for line in fp if line.strip()]


# ---- help -----------------------------------------------------------------


class TestHelp:
    def test_help_prints_usage_and_exits_zero(self, capsys, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        rc = _audit_main(["audit", "help"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "usage: smolcode audit" in out
        assert "ls" in out
        assert "grep" in out
        assert "verify" in out


# ---- ls -------------------------------------------------------------------


class TestLs:
    def test_ls_lists_recent_entries(self, capsys, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        path = tmp_path / "audit.jsonl"
        _write_log(
            path,
            [
                {"event": "start", "tier": "restricted", "task": "echo hi"},
                {"event": "end", "exit_code": 0, "duration_s": 0.1},
            ],
        )
        rc = _audit_main(["audit", "ls", "--audit-log", str(path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "EVENT" in out  # header
        assert "start" in out
        assert "end" in out
        assert "restricted" in out
        assert "echo hi" in out

    def test_ls_with_limit(self, capsys, tmp_path):
        path = tmp_path / "audit.jsonl"
        _write_log(path, [{"event": "step", "step": i} for i in range(10)])
        rc = _audit_main(["audit", "ls", "--audit-log", str(path), "-n", "3"])
        assert rc == 0
        out_lines = [out_line for out_line in capsys.readouterr().out.splitlines() if out_line.strip()]
        # Header + separator + 3 data rows = 5 lines (give or take blank)
        data = [
            out_line
            for out_line in out_lines
            if out_line and not out_line.startswith("TS") and not out_line.startswith("-")
        ]
        assert len(data) == 3

    def test_ls_json_emits_one_json_object_per_line(self, capsys, tmp_path):
        path = tmp_path / "audit.jsonl"
        _write_log(path, [{"event": "start", "task": "x"}, {"event": "end"}])
        rc = _audit_main(["audit", "ls", "--audit-log", str(path), "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        objs = [json.loads(line) for line in out.splitlines() if line.strip()]
        assert len(objs) == 2
        assert objs[0]["event"] == "start"
        assert objs[1]["event"] == "end"

    def test_ls_missing_log_exits_3(self, capsys, tmp_path):
        rc = _audit_main(["audit", "ls", "--audit-log", str(tmp_path / "nope.jsonl")])
        assert rc == 3
        err = capsys.readouterr().err
        assert "not found" in err.lower()

    def test_ls_empty_log_says_empty(self, capsys, tmp_path):
        path = tmp_path / "audit.jsonl"
        path.write_text("", encoding="utf-8")
        rc = _audit_main(["audit", "ls", "--audit-log", str(path)])
        assert rc == 0
        assert "(audit log empty)" in capsys.readouterr().out


# ---- grep -----------------------------------------------------------------


class TestGrep:
    def test_grep_finds_matching_task(self, capsys, tmp_path):
        path = tmp_path / "audit.jsonl"
        _write_log(
            path,
            [
                {"event": "start", "tier": "restricted", "task": "deploy to staging"},
                {"event": "start", "tier": "elevated", "task": "open a PR"},
                {"event": "end"},
            ],
        )
        rc = _audit_main(["audit", "grep", "deploy", "--audit-log", str(path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "deploy to staging" in out
        assert "open a PR" not in out

    def test_grep_case_insensitive(self, capsys, tmp_path):
        path = tmp_path / "audit.jsonl"
        _write_log(path, [{"event": "step", "action": "DEPLOY"}])
        rc = _audit_main(["audit", "grep", "deploy", "--audit-log", str(path)])
        assert rc == 0
        assert "DEPLOY" in capsys.readouterr().out

    def test_grep_no_match_exits_1(self, capsys, tmp_path):
        path = tmp_path / "audit.jsonl"
        _write_log(path, [{"event": "start", "task": "x"}])
        rc = _audit_main(["audit", "grep", "absent", "--audit-log", str(path)])
        assert rc == 1
        assert "(no matches)" in capsys.readouterr().out

    def test_grep_redacts_secrets_in_output(self, capsys, tmp_path):
        """A leaked key in the log must not survive into grep output."""
        path = tmp_path / "audit.jsonl"
        _write_log(
            path,
            [{"event": "error", "kind": "ValueError", "message": "leak sk-abcdefghijklmnop here"}],
        )
        rc = _audit_main(["audit", "grep", "leak", "--audit-log", str(path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "sk-abcdefghijklmnop" not in out
        assert "[REDACTED:openai]" in out

    def test_grep_no_redact_passes_through(self, capsys, tmp_path):
        path = tmp_path / "audit.jsonl"
        _write_log(
            path,
            [{"event": "error", "kind": "ValueError", "message": "leak sk-abcdefghijklmnop"}],
        )
        rc = _audit_main(["audit", "grep", "leak", "--audit-log", str(path), "--no-redact"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "sk-abcdefghijklmnop" in out

    def test_grep_missing_pattern_exits_2(self, capsys, tmp_path):
        rc = _audit_main(["audit", "grep", "--audit-log", str(tmp_path / "x.jsonl")])
        assert rc == 2

    def test_grep_missing_log_exits_3(self, capsys, tmp_path):
        rc = _audit_main(["audit", "grep", "anything", "--audit-log", str(tmp_path / "nope.jsonl")])
        assert rc == 3
        assert "not found" in capsys.readouterr().err.lower()


# ---- verify ---------------------------------------------------------------


class TestVerify:
    def test_verify_clean_log_exits_0(self, capsys, tmp_path):
        path = tmp_path / "audit.jsonl"
        _write_log(
            path,
            [{"event": "start", "task": "x"}, {"event": "end"}],
        )
        rc = _audit_main(["audit", "verify", "--audit-log", str(path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "OK" in out
        assert "chain intact" in out

    def test_verify_tampered_log_exits_1(self, capsys, tmp_path):
        path = tmp_path / "audit.jsonl"
        _write_log(
            path,
            [
                {"event": "start", "task": "x"},
                {"event": "step", "action": "good"},
                {"event": "end"},
            ],
        )
        # Tamper with line 2 (the "step" entry).
        lines = _read_log_lines(path)
        obj = json.loads(lines[1])
        obj["action"] = "bad"
        lines[1] = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        rc = _audit_main(["audit", "verify", "--audit-log", str(path)])
        assert rc == 1
        err = capsys.readouterr().out
        assert "FAIL" in err
        assert "line 2" in err

    def test_verify_pre_m13_log_exits_1_with_partial(self, capsys, tmp_path):
        path = tmp_path / "audit.jsonl"
        # Write a pre-M13 log (no chain fields).
        path.write_text(
            '{"ts":"2020-01-01T00:00:00Z","event":"start","tier":"restricted"}\n',
            encoding="utf-8",
        )
        rc = _audit_main(["audit", "verify", "--audit-log", str(path)])
        assert rc == 1
        out = capsys.readouterr().out
        assert "PARTIAL" in out
        assert "pre-M13" in out

    def test_verify_missing_log_exits_3(self, capsys, tmp_path):
        rc = _audit_main(["audit", "verify", "--audit-log", str(tmp_path / "nope.jsonl")])
        assert rc == 3


# ---- flag / verb errors ---------------------------------------------------


class TestFlagAndVerbErrors:
    def test_unknown_verb_exits_2(self, capsys, tmp_path):
        rc = _audit_main(["audit", "frobnicate", "--audit-log", str(tmp_path / "x.jsonl")])
        assert rc == 2
        assert "unknown audit verb" in capsys.readouterr().err

    def test_ls_with_extra_positional_exits_2(self, capsys, tmp_path):
        path = tmp_path / "audit.jsonl"
        path.write_text("", encoding="utf-8")
        rc = _audit_main(["audit", "ls", "extra", "--audit-log", str(path)])
        assert rc == 2

    def test_n_flag_must_be_int(self, capsys, tmp_path):
        path = tmp_path / "audit.jsonl"
        path.write_text("", encoding="utf-8")
        rc = _audit_main(["audit", "ls", "-n", "abc", "--audit-log", str(path)])
        assert rc == 2

    def test_n_flag_must_be_positive(self, capsys, tmp_path):
        path = tmp_path / "audit.jsonl"
        path.write_text("", encoding="utf-8")
        rc = _audit_main(["audit", "ls", "-n", "0", "--audit-log", str(path)])
        assert rc == 2


# ---- env override ---------------------------------------------------------


class TestEnvOverride:
    def test_sm_env_var_overrides_default_path(self, capsys, tmp_path, monkeypatch):
        path = tmp_path / "audit.jsonl"
        _write_log(path, [{"event": "start", "task": "hi"}])
        monkeypatch.setenv("SMOLCODE_AUDIT_LOG", str(path))
        # No --audit-log; should pick up the env var.
        rc = _audit_main(["audit", "ls"])
        assert rc == 0
        assert "hi" in capsys.readouterr().out


class TestRotate:
    """CLI tests for audit rotate verb (M14.3, decision 0018)."""

    def test_dry_run_prints_plan_exits_zero(self, capsys, tmp_path):
        path = tmp_path / "audit.jsonl"
        _write_log(
            path,
            [
                {"event": "start", "task": "hi"},
                {"event": "end", "exit_code": 0},
            ],
        )
        rc = _audit_main(
            [
                "audit",
                "rotate",
                "--dry-run",
                "--audit-log",
                str(path),
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "(dry-run)" in out
        # File untouched.
        assert path.exists()
        assert path.stat().st_size > 0
        # No archive created.
        assert not list(tmp_path.glob("audit-*.jsonl.gz"))

    def test_rotate_clean_log_exits_zero_creates_gz(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        _write_log(
            path,
            [
                {"event": "start", "task": "hi"},
                {"event": "end", "exit_code": 0},
            ],
        )
        rc = _audit_main(
            [
                "audit",
                "rotate",
                "--keep-days",
                "30",
                "--audit-log",
                str(path),
            ]
        )
        assert rc == 0
        # Live log no longer at the original path; one .gz archive exists.
        assert not path.exists()
        archives = list(tmp_path.glob("audit-*.jsonl.gz"))
        assert len(archives) == 1
        # Decompressing returns the original payload.
        import gzip

        with gzip.open(archives[0], "rt", encoding="utf-8") as fp:
            lines = [ln for ln in fp.read().splitlines() if ln]
        assert len(lines) == 2

    def test_rotate_broken_chain_exits_4_keeps_file(self, capsys, tmp_path):
        path = tmp_path / "audit.jsonl"
        _write_log(
            path,
            [
                {"event": "start", "task": "hi"},
                {"event": "end", "exit_code": 0},
            ],
        )
        # Tamper with the first JSONL line.
        import json as _json

        raw = path.read_text(encoding="utf-8")
        first, _, rest = raw.partition("\n")
        obj = _json.loads(first)
        obj["task"] = "tampered"
        path.write_text(
            _json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n" + rest,
            encoding="utf-8",
        )
        rc = _audit_main(
            [
                "audit",
                "rotate",
                "--audit-log",
                str(path),
            ]
        )
        assert rc == 4
        err = capsys.readouterr().err
        assert "refusing to rotate" in err
        assert "line" in err
        # File unchanged (the size is the same; the bytes may differ if
        # rewriting via JSON was non-canonical, but verify_chain only
        # cared about entry_hash).
        assert path.exists()
        # No archive created.
        assert not list(tmp_path.glob("audit-*.jsonl.gz"))


class TestGrepPatterns:
    """CLI tests for audit grep --patterns (M14.4, decision 0018)."""

    def test_patterns_matches_any_regex(self, capsys, tmp_path):
        path = tmp_path / "audit.jsonl"
        _write_log(
            path,
            [
                {"event": "start", "task": "deploy-prod"},
                {"event": "step", "action": "final_answer"},
                {"event": "start", "task": "rotate-keys"},
                {"event": "error", "kind": "TimeoutError", "message": "boom"},
            ],
        )
        rc = _audit_main(
            [
                "audit",
                "grep",
                "--patterns",
                r"deploy-.*",
                r"Timeout.*",
                "--audit-log",
                str(path),
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        # Two entries should match (deploy-prod and TimeoutError).
        assert "deploy-prod" in out
        assert "TimeoutError" in out
        assert "rotate-keys" not in out
        assert "final_answer" not in out

    def test_patterns_invalid_regex_exits_2(self, capsys, tmp_path):
        path = tmp_path / "audit.jsonl"
        _write_log(path, [{"event": "start", "task": "x"}])
        rc = _audit_main(
            [
                "audit",
                "grep",
                "--patterns",
                r"[unclosed",
                "--audit-log",
                str(path),
            ]
        )
        assert rc == 2
        err = capsys.readouterr().err
        assert "invalid regex" in err

    def test_no_patterns_flag_unchanged_substring(self, capsys, tmp_path):
        """Without --patterns, behavior is case-insensitive substring (M13)."""
        path = tmp_path / "audit.jsonl"
        _write_log(
            path,
            [
                {"event": "start", "task": "Deploy-Prod"},
                {"event": "start", "task": "rotate-keys"},
            ],
        )
        rc = _audit_main(
            [
                "audit",
                "grep",
                "deploy",  # lowercase substring
                "--audit-log",
                str(path),
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "Deploy-Prod" in out
        assert "rotate-keys" not in out

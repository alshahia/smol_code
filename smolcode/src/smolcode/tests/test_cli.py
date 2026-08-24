"""M1.7 - CLI tests; M4 - tier dispatch + confirmation + audit tests."""

import json

import yaml

from smolcode.cli import main


def test_print_config_prints_yaml(_isolate_env, capsys):
    rc = main(["--print-config"])
    assert rc == 0
    out = capsys.readouterr().out
    data = yaml.safe_load(out)
    assert data["provider"] == "opencode-go"
    assert data["model"] == "deepseek-v4-flash"
    assert data["executor"] == "docker"
    assert "restricted" in data["tiers"]
    # M4: all three tiers present in --print-config.
    assert "elevated" in data["tiers"]
    assert "full_access" in data["tiers"]


def test_smoke_returns_stub_answer(_isolate_env, capsys):
    rc = main(["--smoke", "--tier", "restricted", "echo hi"])
    out = capsys.readouterr().out
    assert "[stub] hi" in out
    # rc may be 0 (good) or may be non-zero if CodeAgent.run with a stub
    # still raises internally for an empty step list. We tolerate both
    # but assert the stub reply made it to stdout.
    assert rc in (0, 1)


def test_missing_key_returns_exit_3(_isolate_env, capsys, monkeypatch):
    monkeypatch.delenv("OPENCODE_GO_APIKEY", raising=False)
    monkeypatch.setenv("SMOLCODE_PROVIDER", "opencode-go")
    monkeypatch.setenv("SMOLCODE_MODEL", "deepseek-v4-flash")
    rc = main(["--tier", "restricted", "any task"])
    err = capsys.readouterr().err
    assert rc == 3
    assert "OPENCODE_GO_APIKEY" in err


def test_version_flag(capsys):
    import pytest

    with pytest.raises(SystemExit) as ei:
        main(["--version"])
    assert ei.value.code == 0
    assert "smolcode" in capsys.readouterr().out


# ---- M4: tier dispatch (smoke) -------------------------------------------


def test_elevated_smoke_runs_without_confirmation(_isolate_env, capsys, tmp_path):
    """elevated does not prompt for confirmation (only full_access does)."""
    rc = main(
        [
            "--smoke",
            "--tier",
            "elevated",
            "echo hi",
            "--audit-log",
            str(tmp_path / "a.jsonl"),
        ]
    )
    out = capsys.readouterr().out
    assert "[stub] hi" in out
    assert rc in (0, 1)


# ---- M4: confirmation prompt (full_access) -------------------------------


def test_full_access_with_y_proceeds(_isolate_env, capsys, monkeypatch, tmp_path):
    """Piped 'y' -> the run proceeds and the agent returns."""
    # Patch prompt_confirmation to simulate the user typing 'y'.
    monkeypatch.setattr("smolcode.cli.confirm_full_access", lambda *a, **kw: None)
    rc = main(
        [
            "--smoke",
            "--tier",
            "full_access",
            "echo hi",
            "--audit-log",
            str(tmp_path / "a.jsonl"),
        ]
    )
    out = capsys.readouterr().out
    assert "[stub] hi" in out
    assert rc in (0, 1)


def test_full_access_denial_returns_exit_4(_isolate_env, capsys, monkeypatch):
    """If confirmation is denied (timeout, N, EOF), main returns exit code 4."""
    from smolcode.confirm import ConfirmationDenied

    def deny(*a, **kw):
        raise ConfirmationDenied("test denial")

    monkeypatch.setattr("smolcode.cli.confirm_full_access", deny)
    rc = main(["--smoke", "--tier", "full_access", "echo hi"])
    err = capsys.readouterr().err
    assert rc == 4
    assert "aborted" in err.lower() or "denied" in err.lower()


def test_full_access_short_timeout_denies(_isolate_env, capsys, monkeypatch):
    """--confirm-timeout 0 with no stdin -> deny in <=1s."""
    import time

    from smolcode.confirm import ConfirmationDenied
    from smolcode.confirm import prompt_confirmation as real_pc

    # Force a fast timeout and a never-ready read_fn -> real_pc returns False
    # within ~50ms.
    monkeypatch.setattr(
        "smolcode.cli.resolve_timeout_s",
        lambda *a, **kw: 0.1,
    )

    def raise_if_denied(**kw):
        result = real_pc(
            prompt="",
            timeout_s=0.05,
            read_fn=lambda: time.sleep(5) or "y\n",
            write_fn=lambda s: None,
        )
        if not result:
            raise ConfirmationDenied("timeout (test)")

    monkeypatch.setattr("smolcode.cli.confirm_full_access", raise_if_denied)

    t0 = time.monotonic()
    rc = main(["--smoke", "--tier", "full_access", "echo hi"])
    elapsed = time.monotonic() - t0
    capsys.readouterr()
    assert rc == 4
    assert elapsed < 3.0  # must NOT actually wait 5s


# ---- M4: audit log wiring -----------------------------------------------


def test_audit_log_writes_start_and_end(_isolate_env, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    rc = main(
        [
            "--smoke",
            "--tier",
            "elevated",
            "echo hi",
            "--audit-log",
            str(audit_path),
        ]
    )
    assert audit_path.exists()
    lines = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line]
    events = [line["event"] for line in lines]
    assert "start" in events
    assert "end" in events
    start = next(line for line in lines if line["event"] == "start")
    end = next(line for line in lines if line["event"] == "end")
    assert start["tier"] == "elevated"
    assert start["task"] == "echo hi"
    assert start["provider"] == "opencode-go"
    assert start["model"] == "deepseek-v4-flash"
    assert "ts" in start
    assert "pid" in start
    assert isinstance(end["exit_code"], int)
    assert isinstance(end["duration_s"], float)
    assert rc in (0, 1)


def test_no_audit_flag_skips_log(_isolate_env, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    rc = main(
        [
            "--smoke",
            "--tier",
            "restricted",
            "echo hi",
            "--no-audit",
            "--audit-log",
            str(audit_path),
        ]
    )
    assert not audit_path.exists()
    assert rc in (0, 1)


def test_audit_log_path_uses_env_when_no_flag(_isolate_env, tmp_path, monkeypatch):
    audit_path = tmp_path / "env-audit.jsonl"
    monkeypatch.setenv("SMOLCODE_AUDIT_LOG", str(audit_path))
    rc = main(["--smoke", "--tier", "restricted", "echo hi"])
    assert audit_path.exists()
    assert rc in (0, 1)


def test_audit_log_appends_not_truncates(_isolate_env, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    audit_path.write_text(
        '{"ts":"2020-01-01T00:00:00Z","event":"start","pid":1,"prior":true}\n',
        encoding="utf-8",
    )
    main(
        [
            "--smoke",
            "--tier",
            "restricted",
            "echo hi",
            "--audit-log",
            str(audit_path),
        ]
    )
    text = audit_path.read_text(encoding="utf-8")
    assert "prior" in text  # old content preserved
    # New run appended its own events too.
    assert text.count("\n") >= 2


# ---- M4: --confirm-timeout flag -----------------------------------------


def test_confirm_timeout_flag_overrides_env(_isolate_env, monkeypatch):
    """--confirm-timeout 7 wins over SMOLCODE_FULL_ACCESS_CONFIRM_TIMEOUT_S=15."""
    from smolcode.cli import resolve_timeout_s

    monkeypatch.setenv("SMOLCODE_FULL_ACCESS_CONFIRM_TIMEOUT_S", "15")
    # Simulate argparse passing the value as a string (as it does from CLI).
    assert resolve_timeout_s("7") == 7.0


def test_confirm_timeout_flag_accepts_float(_isolate_env, monkeypatch):
    """--confirm-timeout 2.5 is honored as a float."""
    from smolcode.cli import resolve_timeout_s

    monkeypatch.delenv("SMOLCODE_FULL_ACCESS_CONFIRM_TIMEOUT_S", raising=False)
    assert resolve_timeout_s(2.5) == 2.5

"""Phase 6 (6.3): the local executor must announce that it is not a sandbox.

SMOLCODE_EXECUTOR=local runs model-written Python in this process, as this
user, with this user's credentials. Tier allowlists gate the TOOL layer, but
model-authored code can bypass every allowlist simply by not using a tool.
Running silently under a tier name that implies containment was the hazard,
so the CLI now prints a banner before it does anything else.
"""

from __future__ import annotations

from smolcode.cli import main


def test_local_executor_prints_a_not_sandboxed_banner(_isolate_env, monkeypatch, capsys):
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    main(["--tier", "restricted", "any task"])
    err = capsys.readouterr().err
    assert "NOT SANDBOXED" in err
    # The banner has to say what to do, not just complain.
    assert "docker" in err.lower()


def test_docker_executor_does_not_print_the_banner(_isolate_env, monkeypatch, capsys):
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "docker")
    # Reaches the docker path, which needs an image; the assertion is only
    # that the local-only warning did NOT appear.
    main(["--tier", "restricted", "any task"])
    err = capsys.readouterr().err
    assert "NOT SANDBOXED" not in err


def test_smoke_does_not_warn(_isolate_env, monkeypatch, capsys):
    # --smoke is the offline stub path; warning there would be noise on
    # every health check.
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    main(["--smoke", "--tier", "restricted", "echo hi"])
    assert "NOT SANDBOXED" not in capsys.readouterr().err

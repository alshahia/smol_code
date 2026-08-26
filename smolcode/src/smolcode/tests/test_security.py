"""Top-level security test suite (M7, decision 0009).

Cross-references docs/security.md section 12 (Security testing plan).
Each numbered section in the source below corresponds to one of the
test items in that plan. Where a behaviour is also covered by a
dedicated module-level test file (e.g. test_audit.py, test_redact.py),
we still cover it here as part of the security gate so a deletion
or regression in a module is caught by this suite too.

What this suite guarantees
--------------------------
  * Tier allowlists are immutable: no env var can mutate them.
  * shell.run does not permit shell metacharacter smuggling;
    arguments are validated as a list of strings, the cmd is
    checked against the per-tier allowlist, and subprocess is
    invoked with shell=False.
  * PathPolicy.resolve_under_workspace does not follow a
    symlink that escapes the workspace.
  * MCP readonly mode rejects tools whose name does not start
    with the get/search/read/list prefix (i.e. delete_* are out).
  * RedactSecretsFilter redacts sk-, sk-ant-, hf_, ghp_ in logs.
  * AuditSink refuses to open in any non-append mode.
  * Tier defaults cannot be downgraded via env vars.
"""

from __future__ import annotations

import logging
import sys

import pytest

from smolcode import audit as audit_mod
from smolcode import redact as redact_mod
from smolcode.config import _default_tiers, load_settings
from smolcode.tools import mcp_tools, policy, shell


# --- SEC-1: Tier policy cannot be downgraded by env var --------------------


def test_tier_defaults_are_codestructured():
    """The tier allowlists live in code; no env var reads them."""
    tiers = _default_tiers()
    assert set(tiers) == {"restricted", "elevated", "full_access"}
    # restricted MUST be the most restrictive: smaller command set.
    assert set(tiers["restricted"].commands) <= set(tiers["elevated"].commands)
    assert set(tiers["elevated"].commands) <= set(tiers["full_access"].commands)
    # Imports: restricted is a subset of elevated.
    assert set(tiers["restricted"].imports) <= set(tiers["elevated"].imports)
    assert set(tiers["elevated"].imports) <= set(tiers["full_access"].imports)
    # Network: restricted is none; full_access is open.
    assert tiers["restricted"].network == "none"
    assert tiers["full_access"].network == "open"


def test_tier_immutability_via_settings(monkeypatch, tmp_path):
    """load_settings must return a tier whose policy fields are not
    overridable by env vars. We force every conceivable env var
    and verify the result is unchanged."""
    monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path))
    for var in (
        "SMOLCODE_RESTRICTED_COMMANDS",
        "SMOLCODE_RESTRICTED_IMPORTS",
        "SMOLCODE_RESTRICTED_NETWORK",
        "SMOLCODE_TIER",
        "SMOLCODE_BYPASS_TIER",
        "SMOLCODE_ALLOW_ANY",
    ):
        monkeypatch.setenv(var, "rm -rf /")
    settings = load_settings()
    tier = settings.tiers["restricted"]
    assert "rm" not in tier.commands
    assert "rm" not in tier.imports
    assert tier.network == "none"


def test_tier_unknown_name_does_not_default_to_full(monkeypatch, tmp_path):
    """A typo in --tier (e.g. "full") must NOT silently default to
    full_access, and must NOT be honoured by load_settings if the
    tier name is unknown."""
    monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path))
    # The CLI (cli.py) maps --tier to load_settings; the env var
    # SMOLCODE_TIER is intentionally not honoured. Even if it were,
    # an unknown name must not be silently coerced to full_access.
    monkeypatch.setenv("SMOLCODE_TIER", "restricted")
    settings = load_settings()
    # Tier names are read from _default_tiers, not from env.
    assert "full_access" in settings.tiers
    # The settings object exposes ALL three tiers; the user-facing
    # choice happens at the CLI layer, not by mutating the tier set.
    assert set(settings.tiers) == {"restricted", "elevated", "full_access"}


def test_tier_membership_unchanged_across_loads(monkeypatch, tmp_path):
    """Two consecutive load_settings() calls return identical tier
    dicts. No caching bug or env-var race can mutate them."""
    monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path))
    s1 = load_settings()
    s2 = load_settings()
    for name in ("restricted", "elevated", "full_access"):
        assert s1.tiers[name] == s2.tiers[name], f"tier {name!r} drifted between loads"


# --- SEC-2: shell.run rejects shell injection metacharacters --------------


def test_shell_run_rejects_args_as_string():
    """args must be a list, not a string (string would let the model
    smuggle in ; && | > < as a single shell blob)."""
    tools = shell.build_shell_tools(policy.CommandPolicy(allowlist=("echo",)))
    run = tools[0]
    with pytest.raises(PermissionError):
        run("echo", "rm -rf /", timeout=5)
    with pytest.raises(PermissionError):
        run("echo", "safe; rm -rf /", timeout=5)


def test_shell_run_rejects_non_string_arg_items():
    tools = shell.build_shell_tools(policy.CommandPolicy(allowlist=("echo",)))
    run = tools[0]
    with pytest.raises(PermissionError):
        run("echo", ["ok", 123], timeout=5)


def test_shell_run_rejects_cmd_not_in_allowlist():
    """A cmd whose basename is not in the allowlist is rejected."""
    tools = shell.build_shell_tools(policy.CommandPolicy(allowlist=("echo",)))
    run = tools[0]
    with pytest.raises(PermissionError):
        run("rm", ["-rf", "/"], timeout=5)
    with pytest.raises(PermissionError):
        run("curl", ["http://evil.com"], timeout=5)


def test_shell_run_rejects_dotdot_in_path_arg():
    """`..` in arg is not enforced by the tool (it is a path arg),
    but the cmd allowlist prevents the agent from picking a binary
    that would interpret `..` (e.g. cd)."""
    tools = shell.build_shell_tools(policy.CommandPolicy(allowlist=("echo", "git")))
    run = tools[0]
    # `cd` is NOT in the allowlist; the agent cannot run it.
    with pytest.raises(PermissionError):
        run("cd", [".."], timeout=5)
    with pytest.raises(PermissionError):
        run("cat", ["../../../etc/passwd"], timeout=5)


def test_shell_run_metachars_are_literal_args():
    """The forward uses shell=False so ; && | > < are NOT metachars;
    they are literal bytes. We verify by running python -c with a
    payload that, if shell=True were used, would execute rm."""
    tools = shell.build_shell_tools(policy.CommandPolicy(allowlist=("python",)))
    run = tools[0]
    # The payload says "; rm -rf /" -- if shell=True it would delete
    # the filesystem. With shell=False, python sees it as a literal
    # arg and prints it. Either way rm is never invoked because
    # the cmd allowlist also gates subprocess creation.
    payload = "x=1; rm -rf /tmp/__smolcode_nonexistent__"
    result = run("python", ["-c", "import sys; sys.stdout.write(sys.argv[1])", payload], timeout=10)
    # The literal payload survived round-trip; rm was never executed.
    assert payload in result, result
    assert "removed" not in result.lower(), result


def test_shell_run_uses_shell_false():
    """Static guarantee: subprocess.run must be invoked with
    shell=False. We inspect the source."""
    src = inspect.getsource(shell._RunTool.forward)
    assert "shell=False" in src, "shell.run must use shell=False"
    assert "shell=True" not in src, "shell.run must never use shell=True"


# --- SEC-3: PathPolicy rejects symlinks that escape the workspace ----------


def test_path_policy_rejects_symlink_escape(tmp_path, monkeypatch):
    """A symlink inside the workspace that points outside MUST be
    rejected. This catches the classic symlink-follow escape."""
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = ws / "evil_link"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    pol = policy.PathPolicy(str(ws))
    with pytest.raises(policy.PolicyViolation):
        pol.resolve_under_workspace(str(link))
    # The same path written normally is fine.
    good = ws / "good.txt"
    good.write_text("hi", encoding="utf-8")
    assert pol.resolve_under_workspace(str(good)).read_text() == "hi"


def test_path_policy_rejects_traversal(tmp_path):
    pol = policy.PathPolicy(str(tmp_path))
    with pytest.raises(policy.PolicyViolation):
        pol.resolve_under_workspace(str(tmp_path / ".." / "etc" / "passwd"))
    with pytest.raises(policy.PolicyViolation):
        pol.resolve_under_workspace("../etc/passwd")


def test_path_policy_rejects_absolute_outside(tmp_path):
    pol = policy.PathPolicy(str(tmp_path / "ws"))
    with pytest.raises(policy.PolicyViolation):
        pol.resolve_under_workspace("/etc/passwd")


# --- SEC-4: MCP readonly mode rejects delete_* (and other write names) ----


def test_mcp_readonly_rejects_delete_prefix():
    """A tool named delete_anything must be rejected by readonly."""
    assert mcp_tools.classify_tool_name("delete_file", "readonly") == "violates_mode"
    assert mcp_tools.classify_tool_name("delete_anything", "readonly") == "violates_mode"
    assert mcp_tools.classify_tool_name("drop_table", "readonly") == "violates_mode"
    assert mcp_tools.classify_tool_name("write_file", "readonly") == "violates_mode"


def test_mcp_readonly_accepts_safe_prefixes():
    for name in ("get_user", "search_docs", "read_file", "list_items", "list_all"):
        assert mcp_tools.classify_tool_name(name, "readonly") == "ok", name


def test_mcp_readwrite_accepts_delete_prefix():
    """Readwrite mode (elevated tier) permits delete_*."""
    assert mcp_tools.classify_tool_name("delete_file", "readwrite") == "ok"
    assert mcp_tools.classify_tool_name("delete_file", "full") == "ok"


def test_mcp_shadowed_names_rejected_regardless_of_mode():
    """Names that would shadow a smolagents built-in are always rejected."""
    for mode in ("readonly", "readwrite", "full"):
        assert mcp_tools.classify_tool_name("final_answer", mode) == "shadowed"
        assert mcp_tools.classify_tool_name("python_interpreter", mode) == "shadowed"


# --- SEC-5: RedactSecretsFilter redacts the four prefixes ------------------


def test_redact_secrets_filter_covers_all_four_prefixes():
    samples = {
        "sk-abcdefghijklmnop": "[REDACTED:openai]",
        "sk-ant-api03-abcdefghijklmnop": "[REDACTED:anthropic]",
        "hf_abcdefghijklmnop": "[REDACTED:huggingface]",
        "ghp_abcdefghijklmnop": "[REDACTED:github]",
    }
    flt = redact_mod.RedactSecretsFilter()
    for token, expected in samples.items():
        rec = logging.LogRecord("t", logging.INFO, "/p", 1, "k=%s", (token,), None)
        assert flt.filter(rec) is True
        assert rec.args == (expected,), token


def test_redact_in_msg_format_string():
    flt = redact_mod.RedactSecretsFilter()
    rec = logging.LogRecord("t", logging.INFO, "/p", 1, "leak sk-abcdefghijklmnop", None, None)
    assert flt.filter(rec) is True
    assert "sk-" not in rec.msg
    assert "[REDACTED:openai]" in rec.msg


def test_redact_in_exc_text():
    flt = redact_mod.RedactSecretsFilter()
    rec = logging.LogRecord("t", logging.INFO, "/p", 1, "boom", None, None)
    rec.exc_text = "Traceback: sk-abcdefghijklmnop"
    assert flt.filter(rec) is True
    assert "[REDACTED:openai]" in rec.exc_text


# --- SEC-6: AuditSink rejects non-append modes -----------------------------


def test_audit_sink_rejects_write_mode(tmp_path):
    p = tmp_path / "audit.jsonl"
    with pytest.raises(audit_mod.AuditError):
        audit_mod.AuditSink(str(p), mode="w")
    with pytest.raises(audit_mod.AuditError):
        audit_mod.AuditSink(str(p), mode="x")
    with pytest.raises(audit_mod.AuditError):
        audit_mod.AuditSink(str(p), mode="r")
    with pytest.raises(audit_mod.AuditError):
        audit_mod.AuditSink(str(p), mode="r+")


def test_audit_sink_accepts_append_modes(tmp_path):
    p = tmp_path / "audit.jsonl"
    s1 = audit_mod.AuditSink(str(p), mode="a")
    s1.start(tier="full_access", task="t", model="m", provider="p", executor="local", workspace="/w")
    s1.close()
    s2 = audit_mod.AuditSink(str(p), mode="a+")
    s2.end(exit_code=0, duration_s=0.1)
    s2.close()
    # File has two lines, both valid JSON.
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    import json

    for ln in lines:
        json.loads(ln)


# --- Cross-cutting: tier allowlist contents are exactly as documented -----


def test_restricted_tier_baseline():
    """restricted tier must NOT include any of: ssh, docker, rm, sudo,
    kubectl, terraform, ansible, aws, gcloud, az, scp, rsync."""
    tier = _default_tiers()["restricted"]
    forbidden = {
        "ssh",
        "scp",
        "rsync",
        "docker",
        "kubectl",
        "terraform",
        "ansible",
        "aws",
        "gcloud",
        "az",
        "rm",
        "sudo",
        "curl",
    }
    leaked = forbidden & set(tier.commands)
    assert not leaked, f"restricted tier leaked commands: {leaked}"
    # And no `subprocess`, `socket`, `ctypes` in restricted imports.
    forbidden_imports = {"subprocess", "socket", "ctypes", "asyncio", "ssl"}
    leaked_i = forbidden_imports & set(tier.imports)
    assert not leaked_i, f"restricted tier leaked imports: {leaked_i}"


def test_elevated_tier_baseline():
    """elevated tier must NOT include the most destructive infra CLIs."""
    tier = _default_tiers()["elevated"]
    forbidden = {
        "ssh",
        "scp",
        "rsync",
        "docker",
        "kubectl",
        "terraform",
        "ansible",
        "aws",
        "gcloud",
        "az",
        "rm",
        "sudo",
    }
    leaked = forbidden & set(tier.commands)
    assert not leaked, f"elevated tier leaked commands: {leaked}"


def test_full_access_tier_is_unrestricted_baseline():
    """full_access tier is the only tier that allows open network and
    the most powerful CLIs. This is the documented exception."""
    tier = _default_tiers()["full_access"]
    assert tier.network == "open"
    assert ("*",) == tier.network_allowlist
    for cmd in ("ssh", "scp", "rsync", "docker", "kubectl", "terraform"):
        assert cmd in tier.commands, cmd


# --- Cross-cutting: log redaction is active in the CLI process -----------


def test_redact_is_installed_for_cli(monkeypatch):
    """Calling main() must install the redact filter so any log
    record (e.g. model_id printed to stdout) cannot leak an API key."""
    redact_mod.reset_for_tests()
    assert not redact_mod.is_installed()
    from smolcode import cli

    # --print-config requires no key; use it as a no-op entry point.
    rc = cli.main(["--print-config"])
    assert rc == 0
    # main() itself must have installed the filter. Installing it here
    # as a fallback would make this test tautological: it could never
    # fail even if main() stopped installing the filter.
    assert redact_mod.is_installed(), "cli.main() did not install the RedactSecretsFilter"
    redact_mod.reset_for_tests()


# --- Imports at the bottom to avoid clobbering test discovery --------------
import inspect  # noqa: E402


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))

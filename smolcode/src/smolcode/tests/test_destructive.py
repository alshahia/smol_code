"""M4.x - per-tool destructive-op classification tests.

Covers the heuristic table in `smolcode.destructive`:
  - git_push: always destructive.
  - run with external-surface cmd: always destructive (full_access).
  - run with rm/del/rmdir + recursive/force flag: destructive.
  - run with aws/gcloud/az + destroy/delete subcommand: destructive.
  - git_reset/git_checkout via run with --hard: destructive.
  - everything else: not destructive.

Plus destructive_reason() formatting and the "safe default" behaviour
when given bad input types.
"""

from __future__ import annotations

import pytest

from smolcode.destructive import destructive_reason, is_destructive


# ---- git_push: always destructive -----------------------------------------


class TestGitPush:
    def test_git_push_is_destructive(self):
        assert is_destructive("git_push", {"remote": "origin", "branch": "main"}) is True

    def test_git_push_destructive_with_https_remote(self):
        assert is_destructive("git_push", {"remote": "https://github.com/foo/bar.git", "branch": "main"}) is True

    def test_git_push_destructive_with_no_branch(self):
        assert is_destructive("git_push", {"remote": "origin", "branch": ""}) is True

    def test_git_push_reason_includes_remote_and_branch(self):
        r = destructive_reason("git_push", {"remote": "origin", "branch": "main"})
        assert r is not None
        assert "origin" in r
        assert "main" in r


# ---- run with always-destructive cmd --------------------------------------


class TestRunExternalSurface:
    @pytest.mark.parametrize(
        "cmd",
        [
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
        ],
    )
    def test_external_surface_cmd_always_destructive(self, cmd):
        assert is_destructive("run", {"cmd": cmd, "args": []}) is True

    def test_docker_with_subcommand_destructive(self):
        assert is_destructive("run", {"cmd": "docker", "args": ["ps"]}) is True

    def test_ssh_with_host_destructive(self):
        assert is_destructive("run", {"cmd": "ssh", "args": ["user@host"]}) is True

    def test_kubectl_get_is_still_destructive_v1(self):
        # v1 conservative: any kubectl is gated. False-positive cost
        # is low; user types y once. Better than letting `kubectl
        # delete pod` slip through because the v1 heuristic couldn't
        # parse subcommands.
        assert is_destructive("run", {"cmd": "kubectl", "args": ["get", "pods"]}) is True

    def test_exe_suffix_stripped_for_match(self):
        # Windows: `docker.exe` should match `docker`.
        assert is_destructive("run", {"cmd": "docker.exe", "args": []}) is True

    def test_external_surface_reason_includes_cmd(self):
        r = destructive_reason("run", {"cmd": "docker", "args": ["ps"]})
        assert r is not None
        assert "docker" in r


# ---- run with rm / del + flag ----------------------------------------------


class TestRunFilesystem:
    @pytest.mark.parametrize("flag", ["-rf", "-fr", "-r", "-f", "--force", "--recursive"])
    def test_rm_with_destructive_flag(self, flag):
        assert is_destructive("run", {"cmd": "rm", "args": [flag, "/tmp/x"]}) is True

    @pytest.mark.parametrize("flag", ["/q", "/s", "/f"])
    def test_del_with_windows_flag(self, flag):
        assert is_destructive("run", {"cmd": "del", "args": [flag, "x.txt"]}) is True

    def test_rmdir_always_destructive(self):
        # rmdir is non-recursive by definition but we treat it as
        # destructive for v1 (conservative).
        assert is_destructive("run", {"cmd": "rmdir", "args": ["somedir"]}) is True

    def test_rm_with_glob_is_destructive_even_without_flag(self):
        # `rm *.txt` is a wildcard delete - heuristic catches it.
        assert is_destructive("run", {"cmd": "rm", "args": ["*.txt"]}) is True

    def test_rm_with_question_glob_destructive(self):
        assert is_destructive("run", {"cmd": "rm", "args": ["file?.log"]}) is True

    def test_rm_single_file_no_flag_not_destructive(self):
        # `rm singlefile.txt` is conservative-not-destructive; the
        # tier's command allowlist already lets it through, and a
        # single file rm is recoverable from git. v1 errs on the
        # false-negative side here.
        assert is_destructive("run", {"cmd": "rm", "args": ["singlefile.txt"]}) is False

    def test_del_single_file_no_flag_not_destructive(self):
        assert is_destructive("run", {"cmd": "del", "args": ["singlefile.txt"]}) is False

    def test_ls_not_destructive(self):
        assert is_destructive("run", {"cmd": "ls", "args": []}) is False

    def test_cp_not_destructive(self):
        assert is_destructive("run", {"cmd": "cp", "args": ["a", "b"]}) is False


# ---- run with aws/gcloud/az + destructive subcommand ----------------------


class TestRunCloudCLI:
    @pytest.mark.parametrize(
        "cmd,sub",
        [
            ("aws", "destroy"),
            ("aws", "delete"),
            ("aws", "rm"),
            ("aws", "drop"),
            ("aws", "terminate"),
            ("gcloud", "destroy"),
            ("gcloud", "delete"),
            ("gcloud", "rm"),
            ("az", "delete"),
            ("az", "rm"),
            ("az", "drop"),
        ],
    )
    def test_cloud_cli_with_destructive_subcommand(self, cmd, sub):
        assert is_destructive("run", {"cmd": cmd, "args": [sub, "thing"]}) is True

    @pytest.mark.parametrize(
        "cmd,sub",
        [
            ("aws", "describe"),
            ("aws", "list"),
            ("aws", "get"),
            ("gcloud", "describe"),
            ("gcloud", "list"),
            ("az", "list"),
            ("az", "show"),
        ],
    )
    def test_cloud_cli_with_non_destructive_subcommand(self, cmd, sub):
        # Note: aws/gcloud/az are in the always-destructive set, so
        # ANY call to them is destructive for v1. This test documents
        # the v1 conservative choice.
        assert is_destructive("run", {"cmd": cmd, "args": [sub, "thing"]}) is True


# ---- git_reset / git_checkout via run with --hard --------------------------


class TestRunGitHard:
    def test_run_git_reset_hard_destructive(self):
        # Note: the heuristic matches tool_name in {git_reset,
        # git_checkout}, not the run wrapper. The kwargs shape for
        # these tools carries `extra_args`. This documents the shape
        # that should be passed; in practice git_reset is its own
        # tool, not invoked via run.
        assert is_destructive("git_reset", {"target": "HEAD", "extra_args": ["--hard"]}) is True

    def test_run_git_checkout_hard_destructive(self):
        assert is_destructive("git_checkout", {"target": "main", "extra_args": ["--hard"]}) is True

    def test_run_git_checkout_no_hard_not_destructive(self):
        assert is_destructive("git_checkout", {"target": "main", "extra_args": []}) is False

    def test_run_git_reset_with_hard_equals(self):
        assert is_destructive("git_reset", {"target": "HEAD", "extra_args": ["--hard=HEAD~1"]}) is True

    def test_run_git_reset_with_short_f(self):
        # `-f` is also destructive per spec.
        assert is_destructive("git_reset", {"target": "HEAD", "extra_args": ["-f"]}) is True


# ---- non-destructive sanity -----------------------------------------------


class TestNonDestructive:
    @pytest.mark.parametrize(
        "tool,kwargs",
        [
            ("read_file", {"path": "a.txt"}),
            ("write_file", {"path": "a.txt", "content": "x"}),
            ("list_dir", {"path": "."}),
            ("git_status", {}),
            ("git_diff", {}),
            ("git_log", {}),
            ("git_add", {"paths": ["a"]}),
            ("git_commit", {"message": "x"}),
            ("git_clone", {"url": "x"}),
            ("git_fetch", {"remote": "origin"}),
            ("git_checkout", {"target": "main"}),  # without --hard
        ],
    )
    def test_safe_tools_not_destructive(self, tool, kwargs):
        assert is_destructive(tool, kwargs) is False

    def test_safe_run_python_not_destructive(self):
        assert is_destructive("run", {"cmd": "python", "args": ["-c", "print(1)"]}) is False

    def test_safe_run_pip_install_not_destructive(self):
        assert is_destructive("run", {"cmd": "pip", "args": ["install", "x"]}) is False


# ---- safe defaults on bad input -------------------------------------------


class TestBadInput:
    def test_non_string_tool_name_returns_false(self):
        assert is_destructive(None, {}) is False
        assert is_destructive(123, {}) is False

    def test_non_dict_kwargs_returns_false(self):
        assert is_destructive("git_push", None) is False
        assert is_destructive("git_push", "hello") is False

    def test_unknown_tool_returns_false(self):
        assert is_destructive("totally_made_up", {"x": 1}) is False

    def test_run_with_no_cmd_returns_false(self):
        assert is_destructive("run", {}) is False
        assert is_destructive("run", {"cmd": None}) is False

    def test_run_with_non_list_args_returns_false(self):
        assert is_destructive("run", {"cmd": "rm", "args": "-rf x"}) is False

    def test_destructive_reason_returns_none_for_non_destructive(self):
        assert destructive_reason("read_file", {}) is None
        assert destructive_reason("git_push_unrelated", {}) is None


class TestDestructiveReason:
    def test_reason_for_git_push(self):
        r = destructive_reason("git_push", {"remote": "r", "branch": "b"})
        assert r is not None
        assert "r" in r and "b" in r

    def test_reason_for_run(self):
        r = destructive_reason("run", {"cmd": "docker", "args": ["ps"]})
        assert r is not None
        assert "docker" in r
        assert "ps" in r

    def test_reason_for_git_reset(self):
        r = destructive_reason("git_reset", {"target": "HEAD", "extra_args": ["--hard"]})
        assert r is not None
        assert "HEAD" in r

    def test_reason_for_run_with_no_args(self):
        r = destructive_reason("run", {"cmd": "docker", "args": []})
        assert r is not None
        assert "docker" in r

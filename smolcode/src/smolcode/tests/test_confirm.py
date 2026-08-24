"""M4 + M4.x - confirmation prompt tests."""

import time

import pytest

from smolcode.confirm import (
    ConfirmationDenied,
    confirm_full_access,
    prompt_confirmation,
    prompt_destructive,
    resolve_destructive_timeout_s,
    resolve_timeout_s,
)
from smolcode.session import DestructiveDecision


# ---- resolve_timeout_s ---------------------------------------------------


class TestResolveTimeout:
    def test_default_is_30(self, monkeypatch):
        monkeypatch.delenv("SMOLCODE_FULL_ACCESS_CONFIRM_TIMEOUT_S", raising=False)
        assert resolve_timeout_s() == 30.0

    def test_arg_value_used(self, monkeypatch):
        monkeypatch.delenv("SMOLCODE_FULL_ACCESS_CONFIRM_TIMEOUT_S", raising=False)
        assert resolve_timeout_s("15") == 15.0
        assert resolve_timeout_s(0.5) == 0.5

    def test_arg_overrides_env(self, monkeypatch):
        monkeypatch.setenv("SMOLCODE_FULL_ACCESS_CONFIRM_TIMEOUT_S", "5")
        assert resolve_timeout_s("99") == 99.0

    def test_env_used_when_no_arg(self, monkeypatch):
        monkeypatch.setenv("SMOLCODE_FULL_ACCESS_CONFIRM_TIMEOUT_S", "7")
        assert resolve_timeout_s() == 7.0

    def test_negative_clamped_to_zero(self, monkeypatch):
        monkeypatch.delenv("SMOLCODE_FULL_ACCESS_CONFIRM_TIMEOUT_S", raising=False)
        assert resolve_timeout_s("-5") == 0.0

    def test_unparseable_falls_back_to_30(self, monkeypatch):
        monkeypatch.delenv("SMOLCODE_FULL_ACCESS_CONFIRM_TIMEOUT_S", raising=False)
        assert resolve_timeout_s("abc") == 30.0

    def test_empty_string_falls_back_to_30(self, monkeypatch):
        monkeypatch.setenv("SMOLCODE_FULL_ACCESS_CONFIRM_TIMEOUT_S", "")
        assert resolve_timeout_s() == 30.0


# ---- prompt_confirmation --------------------------------------------------


class TestPromptConfirmation:
    def test_y_returns_true(self):
        assert (
            prompt_confirmation(
                timeout_s=2.0,
                read_fn=lambda: "y\n",
                write_fn=lambda s: None,
            )
            is True
        )

    def test_yes_returns_true(self):
        assert (
            prompt_confirmation(
                timeout_s=2.0,
                read_fn=lambda: "yes\n",
                write_fn=lambda s: None,
            )
            is True
        )

    def test_capital_y_returns_true(self):
        assert (
            prompt_confirmation(
                timeout_s=2.0,
                read_fn=lambda: "Y\n",
                write_fn=lambda s: None,
            )
            is True
        )

    def test_n_returns_false(self):
        assert (
            prompt_confirmation(
                timeout_s=2.0,
                read_fn=lambda: "n\n",
                write_fn=lambda s: None,
            )
            is False
        )

    def test_empty_returns_false(self):
        assert (
            prompt_confirmation(
                timeout_s=2.0,
                read_fn=lambda: "\n",
                write_fn=lambda s: None,
            )
            is False
        )

    def test_garbage_returns_false(self):
        assert (
            prompt_confirmation(
                timeout_s=2.0,
                read_fn=lambda: "maybe\n",
                write_fn=lambda s: None,
            )
            is False
        )

    def test_eof_returns_false(self):
        assert (
            prompt_confirmation(
                timeout_s=2.0,
                read_fn=lambda: "",
                write_fn=lambda s: None,
            )
            is False
        )

    def test_timeout_returns_false(self):
        def slow():
            time.sleep(5)
            return "y\n"

        # Even though user would type y, we must time out first.
        t0 = time.monotonic()
        result = prompt_confirmation(
            timeout_s=0.2,
            read_fn=slow,
            write_fn=lambda s: None,
        )
        elapsed = time.monotonic() - t0
        assert result is False
        assert elapsed < 1.0  # didn't actually wait 5s

    def test_read_exception_returns_false(self):
        def bad():
            raise RuntimeError("boom")

        assert (
            prompt_confirmation(
                timeout_s=2.0,
                read_fn=bad,
                write_fn=lambda s: None,
            )
            is False
        )

    def test_write_exception_is_swallowed(self):
        # write_fn throwing must NOT prevent the read from succeeding.
        def bad_write(s):
            raise RuntimeError("boom")

        assert (
            prompt_confirmation(
                timeout_s=2.0,
                read_fn=lambda: "y\n",
                write_fn=bad_write,
            )
            is True
        )

    def test_timeout_zero_waits_forever(self):
        # timeout_s=0 means "wait forever" (require y even on instant-decline).
        t0 = time.monotonic()
        result = prompt_confirmation(
            timeout_s=0,
            read_fn=lambda: "y\n",
            write_fn=lambda s: None,
        )
        elapsed = time.monotonic() - t0
        assert result is True
        assert elapsed < 0.5  # didn't hang


# ---- confirm_full_access (high-level) ------------------------------------


class TestConfirmFullAccess:
    def test_y_returns_silently(self, monkeypatch):
        monkeypatch.setattr(
            "smolcode.confirm.prompt_confirmation",
            lambda *a, **kw: True,
        )
        confirm_full_access()  # must not raise

    def test_n_raises(self, monkeypatch):
        monkeypatch.setattr(
            "smolcode.confirm.prompt_confirmation",
            lambda *a, **kw: False,
        )
        with pytest.raises(ConfirmationDenied):
            confirm_full_access()

    def test_timeout_message_includes_seconds(self, monkeypatch):
        monkeypatch.setattr(
            "smolcode.confirm.prompt_confirmation",
            lambda *a, **kw: False,
        )
        with pytest.raises(ConfirmationDenied) as ei:
            confirm_full_access(timeout_s=2.5)
        assert "2.5" in str(ei.value) or "timed out" in str(ei.value)


# ---- M4.x: resolve_destructive_timeout_s ----------------------------------


class TestResolveDestructiveTimeout:
    def test_default_is_30(self, monkeypatch):
        monkeypatch.delenv("SMOLCODE_DESTRUCTIVE_CONFIRM_TIMEOUT_S", raising=False)
        assert resolve_destructive_timeout_s() == 30.0

    def test_arg_value_used(self, monkeypatch):
        monkeypatch.delenv("SMOLCODE_DESTRUCTIVE_CONFIRM_TIMEOUT_S", raising=False)
        assert resolve_destructive_timeout_s("12") == 12.0
        assert resolve_destructive_timeout_s(0.5) == 0.5

    def test_arg_overrides_env(self, monkeypatch):
        monkeypatch.setenv("SMOLCODE_DESTRUCTIVE_CONFIRM_TIMEOUT_S", "5")
        assert resolve_destructive_timeout_s("99") == 99.0

    def test_env_used_when_no_arg(self, monkeypatch):
        monkeypatch.setenv("SMOLCODE_DESTRUCTIVE_CONFIRM_TIMEOUT_S", "7")
        assert resolve_destructive_timeout_s() == 7.0

    def test_negative_clamped_to_zero(self, monkeypatch):
        monkeypatch.delenv("SMOLCODE_DESTRUCTIVE_CONFIRM_TIMEOUT_S", raising=False)
        assert resolve_destructive_timeout_s("-5") == 0.0

    def test_unparseable_falls_back_to_30(self, monkeypatch):
        monkeypatch.delenv("SMOLCODE_DESTRUCTIVE_CONFIRM_TIMEOUT_S", raising=False)
        assert resolve_destructive_timeout_s("abc") == 30.0

    def test_empty_string_falls_back_to_30(self, monkeypatch):
        monkeypatch.setenv("SMOLCODE_DESTRUCTIVE_CONFIRM_TIMEOUT_S", "")
        assert resolve_destructive_timeout_s() == 30.0


# ---- M4.x: prompt_destructive ---------------------------------------------


class TestPromptDestructive:
    """Per-tool destructive-op confirmation prompt (decision 0007)."""

    def _capturing_write(self):
        """Return a (write_fn, captured_string_list) pair."""
        captured = []
        return (lambda s: captured.append(s), captured)

    def test_y_approves(self):
        write_fn, captured = self._capturing_write()
        d = prompt_destructive(
            "git_push",
            "remote=origin",
            timeout_s=2.0,
            read_fn=lambda: "y\n",
            write_fn=write_fn,
        )
        assert d.approved is True
        assert d.auto_approve_now is False
        assert d.auto_approve_off is False
        assert "git_push" in captured[0]

    def test_yes_approves(self):
        d = prompt_destructive(
            "run",
            "docker ps",
            timeout_s=2.0,
            read_fn=lambda: "yes\n",
            write_fn=lambda s: None,
        )
        assert d.approved is True

    def test_Y_uppercase_approves(self):
        d = prompt_destructive(
            "git_push",
            "r",
            timeout_s=2.0,
            read_fn=lambda: "Y\n",
            write_fn=lambda s: None,
        )
        assert d.approved is True

    def test_a_approves_and_flips_auto_on(self):
        d = prompt_destructive(
            "git_push",
            "r",
            timeout_s=2.0,
            read_fn=lambda: "a\n",
            write_fn=lambda s: None,
        )
        assert d.approved is True
        assert d.auto_approve_now is True
        assert d.auto_approve_off is False

    def test_all_approves_and_flips_auto_on(self):
        d = prompt_destructive(
            "run",
            "docker rm x",
            timeout_s=2.0,
            read_fn=lambda: "all\n",
            write_fn=lambda s: None,
        )
        assert d.approved is True
        assert d.auto_approve_now is True

    def test_n_denies(self):
        d = prompt_destructive(
            "git_push",
            "r",
            timeout_s=2.0,
            read_fn=lambda: "n\n",
            write_fn=lambda s: None,
        )
        assert d.approved is False
        assert d.auto_approve_off is False

    def test_no_denies(self):
        d = prompt_destructive(
            "git_push",
            "r",
            timeout_s=2.0,
            read_fn=lambda: "no\n",
            write_fn=lambda s: None,
        )
        assert d.approved is False

    def test_o_denies_and_flips_auto_off(self):
        d = prompt_destructive(
            "git_push",
            "r",
            timeout_s=2.0,
            read_fn=lambda: "o\n",
            write_fn=lambda s: None,
        )
        assert d.approved is False
        assert d.auto_approve_off is True

    def test_off_denies_and_flips_auto_off(self):
        d = prompt_destructive(
            "git_push",
            "r",
            timeout_s=2.0,
            read_fn=lambda: "off\n",
            write_fn=lambda s: None,
        )
        assert d.approved is False
        assert d.auto_approve_off is True

    def test_empty_denies(self):
        d = prompt_destructive(
            "git_push",
            "r",
            timeout_s=2.0,
            read_fn=lambda: "\n",
            write_fn=lambda s: None,
        )
        assert d.approved is False
        assert d.reason == "empty"

    def test_garbage_denies(self):
        d = prompt_destructive(
            "git_push",
            "r",
            timeout_s=2.0,
            read_fn=lambda: "maybe\n",
            write_fn=lambda s: None,
        )
        assert d.approved is False
        assert d.reason == "user-denied"

    def test_eof_denies(self):
        d = prompt_destructive(
            "git_push",
            "r",
            timeout_s=2.0,
            read_fn=lambda: "",
            write_fn=lambda s: None,
        )
        assert d.approved is False

    def test_read_exception_denies(self):
        def bad():
            raise RuntimeError("boom")

        d = prompt_destructive(
            "git_push",
            "r",
            timeout_s=2.0,
            read_fn=bad,
            write_fn=lambda s: None,
        )
        assert d.approved is False

    def test_write_exception_is_swallowed(self):
        def bad_write(s):
            raise RuntimeError("boom")

        d = prompt_destructive(
            "git_push",
            "r",
            timeout_s=2.0,
            read_fn=lambda: "y\n",
            write_fn=bad_write,
        )
        assert d.approved is True

    def test_timeout_denies(self):
        def slow():
            time.sleep(5)
            return "y\n"

        t0 = time.monotonic()
        d = prompt_destructive(
            "git_push",
            "r",
            timeout_s=0.2,
            read_fn=slow,
            write_fn=lambda s: None,
        )
        elapsed = time.monotonic() - t0
        assert d.approved is False
        assert elapsed < 1.0

    def test_timeout_zero_waits_forever(self):
        d = prompt_destructive(
            "git_push",
            "r",
            timeout_s=0,
            read_fn=lambda: "y\n",
            write_fn=lambda s: None,
        )
        assert d.approved is True

    def test_prompt_includes_tool_name_and_summary(self):
        captured = []
        prompt_destructive(
            "git_push",
            "remote=origin branch=main",
            timeout_s=2.0,
            read_fn=lambda: "y\n",
            write_fn=lambda s: captured.append(s),
        )
        text = "".join(captured)
        assert "git_push" in text
        assert "remote=origin" in text
        assert "[y/N/a(ll)/o(ff)]" in text

    def test_returns_destructive_decision_instance(self):
        d = prompt_destructive(
            "git_push",
            "r",
            timeout_s=2.0,
            read_fn=lambda: "y\n",
            write_fn=lambda s: None,
        )
        assert isinstance(d, DestructiveDecision)

    def test_auto_approve_now_mid_run_then_subsequent_prompts_skipped(self):
        """If user typed `a`, the cli.py callback should flip
        auto_approve_destructive on the SessionState so subsequent
        prompts are skipped. Tested here via the session module
        because prompt_destructive itself does not mutate the
        session."""
        from smolcode import session as smods

        smods.set_session(smods.SessionState(tier="full_access"))
        d = prompt_destructive(
            "git_push",
            "r",
            timeout_s=2.0,
            read_fn=lambda: "a\n",
            write_fn=lambda s: None,
        )
        assert d.auto_approve_now is True
        # CLI callback would now do: sess.auto_approve_destructive = True.
        sess = smods.current_session()
        sess.auto_approve_destructive = d.auto_approve_now
        assert sess.auto_approve_destructive is True
        smods.set_session(None)

    def test_o_mid_run_disables_subsequent_auto_approve(self):
        from smolcode import session as smods

        smods.set_session(
            smods.SessionState(
                tier="full_access",
                auto_approve_destructive=True,
            )
        )
        d = prompt_destructive(
            "git_push",
            "r",
            timeout_s=2.0,
            read_fn=lambda: "o\n",
            write_fn=lambda s: None,
        )
        assert d.auto_approve_off is True
        sess = smods.current_session()
        sess.auto_approve_destructive = not d.auto_approve_off
        assert sess.auto_approve_destructive is False
        smods.set_session(None)

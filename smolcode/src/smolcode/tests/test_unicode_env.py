"""Tests for smolcode._unicode_env (decision 0024.2).

The helper is idempotent and reconfigures sys.std{out,err,in}.encoding
to UTF-8 with errors='replace'. Tests verify:

  1. The helper reconfigures sys.stdout / sys.stderr / sys.stdin.
  2. The env vars PYTHONIOENCODING / PYTHONUTF8 are set.
  3. Calling the helper twice is a no-op (idempotent).
  4. The helper does not raise even if sys.std* has no "reconfigure"
     method (e.g. test fixtures wrapping stdout).
"""

from __future__ import annotations

import os
import sys

import pytest

from smolcode._unicode_env import setup_unicode_env


@pytest.fixture
def reset_unicode_state(monkeypatch):
    """Snapshot the unicode-related state so each test starts clean.

    The helper is process-global, so we restore _DONE + sys.std* encoding
    + the env vars in teardown so test order doesn't matter.
    """
    import smolcode._unicode_env as mod

    # Reset the global _DONE flag so each test sees the full first-time
    # path.
    monkeypatch.setattr(mod, "_DONE", False)
    # Snapshot env vars and stream encodings.
    saved_env = {k: os.environ.get(k) for k in ("PYTHONIOENCODING", "PYTHONUTF8")}
    saved_stdout_enc = getattr(sys.stdout, "encoding", None)
    saved_stderr_enc = getattr(sys.stderr, "encoding", None)
    saved_stdin_enc = getattr(sys.stdin, "encoding", None)
    yield
    # Restore.
    for k, v in saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    if saved_stdout_enc is not None and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding=saved_stdout_enc)
        except Exception:
            pass
    if saved_stderr_enc is not None and hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding=saved_stderr_enc)
        except Exception:
            pass
    if saved_stdin_enc is not None and hasattr(sys.stdin, "reconfigure"):
        try:
            sys.stdin.reconfigure(encoding=saved_stdin_enc)
        except Exception:
            pass


class TestSetupUnicodeEnv:
    """Decision 0024.2: force UTF-8 stdio so Rich's legacy Windows
    renderer doesn't choke on pip output."""

    def test_reconfigures_stdout_to_utf8(self, reset_unicode_state):
        setup_unicode_env()
        assert sys.stdout.encoding == "utf-8"

    def test_reconfigures_stderr_to_utf8(self, reset_unicode_state):
        setup_unicode_env()
        assert sys.stderr.encoding == "utf-8"

    def test_sets_pythonioencoding_env(self, reset_unicode_state):
        os.environ.pop("PYTHONIOENCODING", None)
        setup_unicode_env()
        assert os.environ.get("PYTHONIOENCODING") == "utf-8"

    def test_sets_pythonutf8_env(self, reset_unicode_state):
        os.environ.pop("PYTHONUTF8", None)
        setup_unicode_env()
        assert os.environ.get("PYTHONUTF8") == "1"

    def test_idempotent(self, reset_unicode_state):
        """Calling twice is a no-op after the first call -- the helper
        sets a module-global _DONE flag. We verify by spying on
        sys.stdout.reconfigure to detect a second invocation."""
        import smolcode._unicode_env as mod

        setup_unicode_env()
        assert mod._DONE is True
        sentinel = {"called": False}
        original_reconfigure = sys.stdout.reconfigure

        def _spy_reconfigure(*a, **kw):
            sentinel["called"] = True
            return original_reconfigure(*a, **kw)

        sys.stdout.reconfigure = _spy_reconfigure
        try:
            setup_unicode_env()
        finally:
            sys.stdout.reconfigure = original_reconfigure
        assert sentinel["called"] is False

    def test_does_not_raise_when_reconfigure_missing(self, reset_unicode_state):
        """A stdout stub without reconfigure (some test fixtures,
        embedded REPLs) must not raise -- the helper swallows reconfigure
        failures and proceeds."""

        class _NoReconfigure:
            encoding = "utf-8"

            def write(self, *_a, **_kw):
                return 0

            def flush(self):
                return None

        original = sys.stdout
        sys.stdout = _NoReconfigure()
        try:
            setup_unicode_env()
        finally:
            sys.stdout = original
        assert os.environ.get("PYTHONIOENCODING") == "utf-8"
        assert os.environ.get("PYTHONUTF8") == "1"

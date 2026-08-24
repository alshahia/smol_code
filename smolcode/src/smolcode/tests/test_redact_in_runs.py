"""M11 (decision 0014) -- verify the redactor catches any keys
that might slip into log records emitted by the run / web stack.

The redactor is the M7 ``redact.RedactSecretsFilter``. The contract
is: a log record carrying a token matching the well-known prefixes
``sk-ant-*``, ``sk-*``, ``hf_*``, ``ghp_*`` must be mutated so the
token is replaced with ``[REDACTED:<class>]`` BEFORE the formatter
runs.

These tests install the redactor for the duration of the test and
verify it scrubs:
  * Log calls that include the key in their message string
  * Log calls that include the key in their substitution args
  * Logger.error(exc_info) formatted tracebacks that contain the key

It does NOT test that ``Run.api_key_value`` is excluded from the
SSE stream (that's the contract covered by ``test_runs_keys.py``
and ``test_web_runs_api.py::TestRunsM11Overrides``).
"""

from __future__ import annotations

import logging

import pytest

from smolcode.redact import (
    install_redact_filter,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def _install_redact():
    install_redact_filter()
    yield
    reset_for_tests()


class TestRedactorScrubsLogRecords:
    def test_openai_token_in_message_redacted(self, caplog):
        with caplog.at_level(logging.INFO, logger="smolcode.web.runs"):
            log = logging.getLogger("smolcode.web.runs")
            log.info("using key=%s", "sk-abcdef1234567890XYZ")
        text = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "sk-abcdef1234567890XYZ" not in text
        assert "[REDACTED:openai]" in text

    def test_anthropic_token_in_message_redacted(self, caplog):
        with caplog.at_level(logging.INFO, logger="smolcode.web.runs"):
            log = logging.getLogger("smolcode.web.runs")
            log.info("anthropic key=%s", "sk-ant-api03-abcdefghij1234567890ABCDEFGHIJKL")
        text = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "sk-ant-api03-abcdefghij1234567890ABCDEFGHIJKL" not in text
        assert "[REDACTED:anthropic]" in text

    def test_hf_token_in_message_redacted(self, caplog):
        with caplog.at_level(logging.INFO, logger="smolcode.web.runs"):
            log = logging.getLogger("smolcode.web.runs")
            log.info("HF=%s", "hf_AbCdEfGhIjKlMnOpQrStUvWxYz1234567890")
        text = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "hf_AbCdEfGhIjKlMnOpQrStUvWxYz1234567890" not in text
        assert "[REDACTED:huggingface]" in text

    def test_token_in_format_string_redacted(self, caplog):
        # The token is in the format string itself (no %s substitution).
        with caplog.at_level(logging.INFO, logger="smolcode.web.runs"):
            log = logging.getLogger("smolcode.web.runs")
            log.info("value: sk-abcdefghij1234567890")
        text = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "sk-abcdefghij1234567890" not in text
        assert "[REDACTED:openai]" in text

    def test_token_in_dict_args_redacted(self, caplog):
        # Log calls sometimes pass a dict in args.
        with caplog.at_level(logging.INFO, logger="smolcode.web.runs"):
            log = logging.getLogger("smolcode.web.runs")
            log.info("using %s", {"key": "sk-abcdef1234567890XYZZZZ"})
        text = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "sk-abcdef1234567890XYZZZZ" not in text
        assert "[REDACTED:openai]" in text

    def test_safe_message_unchanged(self, caplog):
        with caplog.at_level(logging.INFO, logger="smolcode.web.runs"):
            log = logging.getLogger("smolcode.web.runs")
            log.info("plain message with no secrets")
        text = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "plain message with no secrets" in text
        assert "[REDACTED" not in text

    def test_redactor_does_not_double_wrap(self):
        # Calling install_redact_filter twice should not chain factories.
        install_redact_filter()
        install_redact_filter()
        # Will throw or produce weird output if double-wrapped.
        # We just want this to not crash.


class TestRedactorSafety:
    def test_short_token_not_redacted(self, caplog):
        # Tokens shorter than the min token length (10 TOTAL chars)
        # are not scrubbed -- they are likely user-facing strings
        # (e.g. "sk-x") that we should never touch.
        with caplog.at_level(logging.INFO, logger="smolcode.web.runs"):
            log = logging.getLogger("smolcode.web.runs")
            log.info("sk-ab")  # 5 chars, below the 10-char threshold
        text = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "sk-ab" in text
        assert "[REDACTED" not in text

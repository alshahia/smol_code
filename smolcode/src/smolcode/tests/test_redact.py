"""Unit tests for smolcode.redact (M7, decision 0009).

Covers:
  * DEFAULT_PATTERNS recognises all nine secret prefixes (M7 + M13).
  * redact_string replaces each kind with a [REDACTED:<class>] marker.
  * sk-ant- is NOT re-matched by the sk- pattern (marker does not contain sk-).
  * Short tokens (under min_token_len) are NOT redacted.
  * RedactSecretsFilter mutates LogRecord.msg / args / exc_text.
  * install_redact_filter uses setLogRecordFactory and is idempotent.
  * reset_for_tests restores the previous factory.
  * Nested structures in args (dict, list) are walked.
  * Custom patterns can be added at construction time.
"""

from __future__ import annotations

import logging
import re

import pytest

from smolcode.redact import (
    DEFAULT_PATTERNS,
    MIN_TOKEN_LEN,
    RedactSecretsFilter,
    _redact_args,
    _redact_value,
    install_redact_filter,
    is_installed,
    redact_string,
    reset_for_tests,
)


# --- Module-level constants ---------------------------------------------------


def test_default_patterns_has_nine_prefixes():
    """M7 had 4 prefixes; M13 expanded to 9 (Google/AWS/GitHub-OAuth/User/Server)."""
    assert len(DEFAULT_PATTERNS) == 9
    literals = [p.pattern for p in DEFAULT_PATTERNS]
    # M7 set
    assert any("sk-ant-" in lit for lit in literals)
    assert any("sk-" in lit for lit in literals)
    assert any("hf_" in lit for lit in literals)
    assert any("ghp_" in lit for lit in literals)
    # M13 additions
    assert any("gho_" in lit for lit in literals), "missing gho_ (GitHub OAuth)"
    assert any("ghu_" in lit for lit in literals), "missing ghu_ (GitHub user)"
    assert any("ghs_" in lit for lit in literals), "missing ghs_ (GitHub server)"
    assert any("AIza" in lit for lit in literals), "missing AIza (Google)"
    assert any("AKIA" in lit for lit in literals), "missing AKIA (AWS)"


def test_default_patterns_order_sk_ant_before_sk():
    """The sk- pattern must come AFTER sk-ant- so the longer match wins."""
    literals = [p.pattern for p in DEFAULT_PATTERNS]
    sk_ant_idx = next(i for i, lit in enumerate(literals) if "sk-ant-" in lit)
    sk_idx = next(i for i, lit in enumerate(literals) if lit.startswith("sk-["))
    assert sk_ant_idx < sk_idx, "sk-ant- must precede sk- in DEFAULT_PATTERNS"


def test_min_token_len_is_sensible():
    assert MIN_TOKEN_LEN >= 6, "min token length should be high enough to avoid over-redaction"
    assert MIN_TOKEN_LEN <= 64, "min token length should be low enough to match real tokens"


# --- redact_string ----------------------------------------------------------


def test_redact_openai_sk_prefix():
    s, n = redact_string("key=sk-abcdefghijklmnop", DEFAULT_PATTERNS)
    assert s == "key=[REDACTED:openai]"
    assert n == 1


def test_redact_anthropic_sk_ant_prefix():
    s, n = redact_string("k=sk-ant-api03-abcdefghijklmnop", DEFAULT_PATTERNS)
    assert s == "k=[REDACTED:anthropic]"
    assert n == 1


def test_redact_huggingface_hf_prefix():
    s, n = redact_string("hf_abcdefghijklmnop", DEFAULT_PATTERNS)
    assert s == "[REDACTED:huggingface]"
    assert n == 1


def test_redact_github_ghp_prefix():
    s, n = redact_string("token=ghp_abcdefghijklmnop", DEFAULT_PATTERNS)
    assert s == "token=[REDACTED:github]"
    assert n == 1


def test_redact_sk_ant_marker_does_not_contain_sk():
    """Regression: the sk- pattern would re-match [REDACTED-sk-ant]."""
    s, _ = redact_string("k=sk-ant-api03-abcdefghijklmnop", DEFAULT_PATTERNS)
    # The redaction marker MUST NOT itself contain "sk-" or it would be
    # re-matched by the next pattern pass.
    assert "sk-" not in s
    assert "[REDACTED:anthropic]" in s


def test_redact_no_false_positive_on_short_strings():
    """Strings shorter than MIN_TOKEN_LEN after the prefix are left alone."""
    # MIN_TOKEN_LEN is 10, so "sk-short" (after "sk-": 5 chars) is safe.
    s, n = redact_string("sk-short", DEFAULT_PATTERNS)
    assert s == "sk-short"
    assert n == 0


def test_redact_passes_through_unrelated_strings():
    s, n = redact_string("just a normal log line with no secrets", DEFAULT_PATTERNS)
    assert s == "just a normal log line with no secrets"
    assert n == 0


def test_redact_handles_multiple_secrets_in_one_string():
    s, n = redact_string("a=sk-abcdefghijklmnop b=hf_abcdefghijklmnop", DEFAULT_PATTERNS)
    assert s == "a=[REDACTED:openai] b=[REDACTED:huggingface]"
    assert n == 2


# --- _redact_value / _redact_args -------------------------------------------


def test_redact_value_string():
    assert _redact_value("sk-abcdefghijklmnop", DEFAULT_PATTERNS) == "[REDACTED:openai]"


def test_redact_value_int_unchanged():
    assert _redact_value(42, DEFAULT_PATTERNS) == 42


def test_redact_value_none_unchanged():
    assert _redact_value(None, DEFAULT_PATTERNS) is None


def test_redact_args_tuple():
    out = _redact_args(("sk-abcdefghijklmnop", "safe"), DEFAULT_PATTERNS)
    assert out == ("[REDACTED:openai]", "safe")


def test_redact_args_dict():
    out = _redact_args({"key": "sk-abcdefghijklmnop"}, DEFAULT_PATTERNS)
    assert out == {"key": "[REDACTED:openai]"}


def test_redact_args_none():
    assert _redact_args(None, DEFAULT_PATTERNS) is None


def test_redact_args_nested_list():
    out = _redact_args((["sk-abcdefghijklmnop", "safe"],), DEFAULT_PATTERNS)
    # List children are walked recursively; outer container is normalized to tuple.
    assert out == (("[REDACTED:openai]", "safe"),)


# --- RedactSecretsFilter -----------------------------------------------------


def test_filter_mutates_msg_with_secret():
    flt = RedactSecretsFilter()
    rec = logging.LogRecord("n", logging.INFO, "/p", 1, "key %s", None, None)
    rec.msg = "leak sk-abcdefghijklmnop here"
    assert flt.filter(rec) is True
    assert rec.msg == "leak [REDACTED:openai] here"
    assert getattr(rec, "redacted_count", 0) == 1


def test_filter_mutates_args_with_secret():
    flt = RedactSecretsFilter()
    rec = logging.LogRecord("n", logging.INFO, "/p", 1, "k %s", ("sk-abcdefghijklmnop",), None)
    assert flt.filter(rec) is True
    assert rec.args == ("[REDACTED:openai]",)
    assert rec.getMessage() == "k [REDACTED:openai]"


def test_filter_mutates_exc_text():
    flt = RedactSecretsFilter()
    rec = logging.LogRecord("n", logging.INFO, "/p", 1, "boom", None, None)
    rec.exc_text = "Traceback: leaked sk-abcdefghijklmnop"
    assert flt.filter(rec) is True
    assert "sk-" not in rec.exc_text
    assert "[REDACTED:openai]" in rec.exc_text


def test_filter_returns_true_for_safe_record():
    flt = RedactSecretsFilter()
    rec = logging.LogRecord("n", logging.INFO, "/p", 1, "ok %s", ("safe",), None)
    assert flt.filter(rec) is True
    assert rec.args == ("safe",)
    assert not hasattr(rec, "redacted_count") or rec.redacted_count == 0


def test_filter_rejects_non_compiled_patterns():
    with pytest.raises(TypeError):
        RedactSecretsFilter(patterns=["sk-..."])  # strings, not compiled


def test_filter_accepts_extra_patterns():
    flt = RedactSecretsFilter(patterns=[re.compile(r"xoxb-[A-Za-z0-9]+")])
    rec = logging.LogRecord("n", logging.INFO, "/p", 1, "t=%s", ("xoxb-1234567890abcdef",), None)
    assert flt.filter(rec) is True
    assert rec.args == ("[REDACTED]",)


# --- install / reset / is_installed -----------------------------------------


def test_install_returns_filter():
    reset_for_tests()
    flt = install_redact_filter()
    try:
        assert isinstance(flt, RedactSecretsFilter)
        assert is_installed()
    finally:
        reset_for_tests()


def test_install_is_idempotent():
    reset_for_tests()
    flt1 = install_redact_filter()
    flt2 = install_redact_filter()
    try:
        assert flt1 is flt2, "second install must return the same filter"
    finally:
        reset_for_tests()


def test_install_wires_record_factory():
    reset_for_tests()
    factory = logging.getLogRecordFactory()
    install_redact_filter()
    try:
        new_factory = logging.getLogRecordFactory()
        assert new_factory is not factory
        assert getattr(new_factory, "_smolcode_redact_wrapped", False) is True
    finally:
        reset_for_tests()


def test_install_factory_redacts_real_log():
    """End-to-end: install the factory, log through a real handler."""
    reset_for_tests()
    install_redact_filter()
    try:
        buf = []
        handler = logging.StreamHandler(_ListHandler(buf))
        handler.setFormatter(logging.Formatter("%(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        old_level = root.level
        root.setLevel(logging.INFO)
        try:
            logging.getLogger("test").info("key %s", "sk-abcdefghijklmnop")
        finally:
            root.setLevel(old_level)
            root.removeHandler(handler)
        assert len(buf) == 1
        assert "sk-" not in buf[0]
        assert "[REDACTED:openai]" in buf[0]
    finally:
        reset_for_tests()


def test_reset_restores_previous_factory():
    reset_for_tests()
    factory_before = logging.getLogRecordFactory()
    install_redact_filter()
    assert logging.getLogRecordFactory() is not factory_before
    reset_for_tests()
    assert logging.getLogRecordFactory() is factory_before
    assert not is_installed()


def test_reset_idempotent_when_not_installed():
    reset_for_tests()
    factory = logging.getLogRecordFactory()
    reset_for_tests()  # second call is a no-op
    reset_for_tests()  # third call too
    assert logging.getLogRecordFactory() is factory


def test_reset_then_reinstall():
    """After reset, install_redact_filter must work again."""
    reset_for_tests()
    install_redact_filter()
    reset_for_tests()
    flt = install_redact_filter()
    try:
        assert isinstance(flt, RedactSecretsFilter)
        assert is_installed()
    finally:
        reset_for_tests()


# --- Helpers -----------------------------------------------------------------


class _ListHandler:
    """Minimal stream-like sink that appends to a list."""

    def __init__(self, sink):
        self._sink = sink

    def write(self, msg):
        self._sink.append(msg.rstrip("\n"))
        return len(msg)

    def flush(self):
        pass


# --- M13: additional prefixes (decision 0016) -----------------------------


def test_redact_github_oauth_gho_prefix():
    s, n = redact_string("oauth=gho_abcdefghijklmnop", DEFAULT_PATTERNS)
    assert s == "oauth=[REDACTED:github-oauth]"
    assert n == 1


def test_redact_github_user_ghu_prefix():
    s, n = redact_string("user=ghu_abcdefghijklmnop", DEFAULT_PATTERNS)
    assert s == "user=[REDACTED:github-user]"
    assert n == 1


def test_redact_github_server_ghs_prefix():
    s, n = redact_string("server=ghs_abcdefghijklmnop", DEFAULT_PATTERNS)
    assert s == "server=[REDACTED:github-server]"
    assert n == 1


def test_redact_google_aiza_prefix():
    s, n = redact_string("k=AIzaSyD-abcdefghijklmnop", DEFAULT_PATTERNS)
    assert s == "k=[REDACTED:google]"
    assert n == 1


def test_redact_aws_akia_prefix():
    s, n = redact_string("id=AKIAIOSFODNN7EXAMPLE", DEFAULT_PATTERNS)
    assert s == "id=[REDACTED:aws]"
    assert n == 1


def test_redact_handles_multiple_secrets_one_string_m13():
    """Mix of M7 + M13 prefixes in one string; each redacted independently."""
    s, n = redact_string(
        "a=sk-abcdefghijklmnop b=AIzaSyD-abcdefghijklmnop c=AKIAIOSFODNN7EXAMPLE",
        DEFAULT_PATTERNS,
    )
    assert s == "a=[REDACTED:openai] b=[REDACTED:google] c=[REDACTED:aws]"
    assert n == 3


def test_marker_names_do_not_contain_trigger_prefix():
    """Regression: no [REDACTED:...] marker should re-trigger any prefix regex."""
    from smolcode.redact import _PATTERN_PREFIX

    all_prefixes = ["sk-ant-", "sk-", "hf_", "ghp_", "gho_", "ghu_", "ghs_", "AIza", "AKIA"]
    for prefix, marker in _PATTERN_PREFIX.items():
        assert not marker.startswith(prefix), (
            f"marker {marker!r} starts with trigger prefix {prefix!r} - would re-match"
        )
    # Also ensure marker names do not start with any OTHER prefix either.
    for marker in _PATTERN_PREFIX.values():
        for prefix in all_prefixes:
            assert not marker.startswith(prefix), f"marker {marker!r} collides with prefix {prefix!r}"


def test_redact_filter_end_to_end_with_m13_prefixes():
    """End-to-end: install the factory, log a real Google/AWS token, see redacted output."""
    reset_for_tests()
    install_redact_filter()
    try:
        buf = []
        handler = logging.StreamHandler(_ListHandler(buf))
        handler.setFormatter(logging.Formatter("%(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        old_level = root.level
        root.setLevel(logging.INFO)
        try:
            logging.getLogger("test").info(
                "google=%s aws=%s",
                "AIzaSyD-abcdefghijklmnop",
                "AKIAIOSFODNN7EXAMPLE",
            )
        finally:
            root.setLevel(old_level)
            root.removeHandler(handler)
        assert len(buf) == 1
        assert "AIza" not in buf[0]
        assert "AKIA" not in buf[0]
        assert "[REDACTED:google]" in buf[0]
        assert "[REDACTED:aws]" in buf[0]
    finally:
        reset_for_tests()


# --- M15.2: redact_string public surface (decision 0019) --------------------


def test_redact_string_default_patterns_when_none_passed():
    """M15.2: omitting `patterns` falls back to DEFAULT_PATTERNS.

    The public helper is callable with a single positional arg;
    it must redact every known secret prefix without the caller
    having to import DEFAULT_PATTERNS themselves.
    """
    s, n = redact_string("key=sk-abcdefghijklmnop")
    assert n == 1
    assert s == "key=[REDACTED:openai]"
    # Multi-prefix case to prove DEFAULT_PATTERNS (not just one pattern) is active.
    s, n = redact_string("a=sk-abcdefghijklmnop b=hf_abcdefghijklmnop c=AIzaSyD-abcdefghijklmnop")
    assert n == 3
    assert "[REDACTED:openai]" in s
    assert "[REDACTED:huggingface]" in s
    assert "[REDACTED:google]" in s


def test_redact_string_custom_patterns_replace_defaults():
    """M15.2: passing a `patterns` list REPLACES (not augments) DEFAULT_PATTERNS.

    Contract: callers who want both must pass
    ``list(DEFAULT_PATTERNS) + extra_patterns``.
    """
    import re as _re

    # Custom-only: only the JWT pattern matches; DEFAULT_PATTERNS do NOT run.
    # Real JWTs look like `eyJ<header>.eyJ<signature>`; the test fixture
    # uses both segments so the pattern's `\.eyJ...` actually fires.
    jwt_pat = _re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}")
    jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
    s, n = redact_string("jwt=" + jwt_token + " secret=sk-abcdefghijklmnop", patterns=[jwt_pat])
    # The JWT pattern matched both segments but sk- did NOT (defaults disabled).
    assert jwt_token not in s
    assert "[REDACTED]" in s
    assert "sk-abcdefghijklmnop" in s  # default patterns are off

    # Combined: DEFAULT_PATTERNS + extra. This is the recommended usage.
    combined = list(DEFAULT_PATTERNS) + [jwt_pat]
    s, n = redact_string("sk=sk-abcdefghijklmnop jwt=" + jwt_token, patterns=combined)
    assert "[REDACTED:openai]" in s
    assert "[REDACTED]" in s  # jwt pattern uses the catch-all [REDACTED] marker

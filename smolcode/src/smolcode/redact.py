"""Secret redacting logging filter (M7, decision 0009; expanded M13, decision 0016).

A logging.Filter that replaces well-known secret prefixes in every
log record's message before the formatter reads it. Recognised
prefixes (case-sensitive):

    * sk-      -- OpenAI
    * sk-ant-  -- Anthropic (must precede sk-)
    * hf_      -- HuggingFace
    * ghp_     -- GitHub Personal Access Token
    * gho_     -- GitHub OAuth Access Token  (M13)
    * ghu_     -- GitHub User Token         (M13)
    * ghs_     -- GitHub Server Token       (M13)
    * AIza     -- Google API key            (M13)
    * AKIA     -- AWS access key ID         (M13)

The filter mutates record.msg (the format string), each string in
record.args (the substitution values), and record.exc_text (the
formatted traceback). Strings shorter than MIN_TOKEN_LEN (default
10) characters are left alone so we do not over-redact.

Per docs/security.md section 8 the redactor must be wired into the
root logger so audit / orchestrator / specialist logs cannot leak
API keys. The CLI installs it via install_redact_filter() which is
idempotent.

Usage::

    import logging, smolcode.redact
    smolcode.redact.install_redact_filter()
    logging.info("using key %s", "sk-abcdef1234567890XYZ")

The second argument will be redacted; the log line will read::

    using key [REDACTED:openai]

Each redacted fragment is replaced with a "[REDACTED:<class>]"
marker (e.g. "[REDACTED:openai]", "[REDACTED:anthropic]",
"[REDACTED:huggingface]", "[REDACTED:github]") so the operator can
see *that* a redaction occurred and the class of token, without
learning the value.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable, Sequence


# Prefix length table; matched longest-first so prefix order is
# predictable. The token class is encoded in the redaction marker so
# operators can confirm the filter caught the right kind of secret.
DEFAULT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-ant-[A-Za-z0-9_-]+"),
    re.compile(r"sk-[A-Za-z0-9_-]+"),
    re.compile(r"hf_[A-Za-z0-9]+"),
    re.compile(r"ghp_[A-Za-z0-9]+"),
    # M13: GitHub OAuth / user / server tokens. Each has a distinct
    # 4th character so no overlap with ghp_. All GitHub markers are
    # plain English ("github-oauth" etc.) so they cannot be re-matched.
    re.compile(r"gho_[A-Za-z0-9]+"),
    re.compile(r"ghu_[A-Za-z0-9]+"),
    re.compile(r"ghs_[A-Za-z0-9]+"),
    # M13: Google API keys (AIza prefix, case-sensitive).
    re.compile(r"AIza[A-Za-z0-9_-]+"),
    # M13: AWS access key IDs (AKIA prefix, uppercase letters + digits).
    re.compile(r"AKIA[A-Z0-9]+"),
)

# Minimum trailing characters after the prefix. Avoids redacting
# common short references like "sk-empty" or "ghp_short".
MIN_TOKEN_LEN = 10

# A pattern's "short prefix" is the literal characters before the
# variable-length token class. We capture them so the redaction
# marker can name the token class.
# A pattern marker uses a colon-separated name that does NOT
# contain the trigger prefix (so the redaction marker itself
# cannot be re-redacted by a later pass). The keys here are the
# exact literal prefixes the regex requires at the start of the
# token; the values are the marker names emitted in the log.
_PATTERN_PREFIX = {
    "sk-ant-": "anthropic",
    "sk-": "openai",
    "hf_": "huggingface",
    "ghp_": "github",
    # M13: GitHub family tokens get distinct marker names so an
    # operator can see the KIND of GitHub token that was redacted.
    "gho_": "github-oauth",
    "ghu_": "github-user",
    "ghs_": "github-server",
    "AIza": "google",
    "AKIA": "aws",
}


def redact_string(s, patterns=None, min_token_len=MIN_TOKEN_LEN):
    """Public redaction helper (M15.2, decision 0019).

    Return (scrubbed_string, redaction_count).

    Each matched secret is replaced with "[REDACTED:<class>]" where
    <class> is the marker name in _PATTERN_PREFIX (one of
    "openai", "anthropic", "huggingface", "github", etc.).

    Args:
        s: input string to scrub.
        patterns: optional iterable of compiled regex patterns.
            When ``None`` (the default), ``DEFAULT_PATTERNS`` is used.
            When provided, the iterable REPLACES the defaults —
            callers who want both should pass
            ``list(DEFAULT_PATTERNS) + custom_patterns``.
            This is the public helper that replaces the prior
            private ``_redact_string`` (M13) — the third-party
            integration surface promised in `docs/security.md` §8.
        min_token_len: minimum length of the matched token (after the
            prefix) before it is redacted. Defaults to
            ``MIN_TOKEN_LEN`` (10) to avoid truncating short,
            non-secret strings that happen to start with one of the
            prefixes.

    IMPORTANT: the redaction marker does not contain the trigger
    substring, so it cannot be re-matched by a later pattern. This
    is critical for sk-ant- (whose marker would otherwise contain sk-).
    """
    count = 0

    def _sub(match):
        nonlocal count
        token = match.group(0)
        if min_token_len and len(token) < min_token_len:
            return token
        count += 1
        for prefix, label in _PATTERN_PREFIX.items():
            if token.startswith(prefix):
                return "[REDACTED:" + label + "]"
        return "[REDACTED]"

    if patterns is None:
        patterns = DEFAULT_PATTERNS
    for pattern in patterns:
        s = pattern.sub(_sub, s)
    return s, count


def _redact_args(args, patterns: Sequence[re.Pattern[str]], min_token_len: int = MIN_TOKEN_LEN):
    """Walk an args tuple/dict (or scalar) and redact string members."""
    if args is None:
        return args
    if isinstance(args, dict):
        return {k: _redact_value(v, patterns, min_token_len) for k, v in args.items()}
    if isinstance(args, (tuple, list)):
        return tuple(_redact_value(a, patterns, min_token_len) for a in args)
    return _redact_value(args, patterns, min_token_len)


def _redact_value(value, patterns: Sequence[re.Pattern[str]], min_token_len: int = MIN_TOKEN_LEN):
    if isinstance(value, str):
        scrubbed, _ = redact_string(value, patterns, min_token_len)
        return scrubbed
    if isinstance(value, (tuple, list)):
        return tuple(_redact_value(v, patterns, min_token_len) for v in value)
    if isinstance(value, dict):
        return {k: _redact_value(v, patterns, min_token_len) for k, v in value.items()}
    return value


class RedactSecretsFilter(logging.Filter):
    """Logging filter that scrubs known secret prefixes from log records.

    Args:
        patterns: optional extra regex patterns to match. Useful in
            tests for asserting edge cases (e.g. self-signed JWTs).
        min_token_len: minimum length of the matched token (after the
            prefix) before it is redacted. Defaults to 10 to avoid
            truncating short, non-secret strings that happen to start
            with one of the prefixes.

    The filter mutates the record in place; it does not format it.
    Install with addFilter on the root logger or on a specific
    handler. The CLI installs it on the root logger at startup via
    install_redact_filter().
    """

    def __init__(
        self,
        patterns: Iterable[re.Pattern[str]] = DEFAULT_PATTERNS,
        min_token_len: int = MIN_TOKEN_LEN,
    ) -> None:
        super().__init__()
        compiled: list[re.Pattern[str]] = []
        for pat in patterns:
            if isinstance(pat, re.Pattern):
                compiled.append(pat)
            else:
                raise TypeError("patterns must be compiled regex objects, got " + repr(type(pat)))
        self.patterns: tuple[re.Pattern[str], ...] = tuple(compiled)
        self.min_token_len = int(min_token_len)

    def filter(self, record: logging.LogRecord) -> bool:
        # Always True; we mutate rather than drop.
        redacted = 0
        min_len = self.min_token_len
        # 1. The format string itself.
        if isinstance(record.msg, str):
            scrubbed, n = redact_string(record.msg, self.patterns, min_len)
            if n:
                record.msg = scrubbed
                redacted += n
        # 2. The substitution args (tuple, dict, or scalar).
        if record.args:
            new_args = _redact_args(record.args, self.patterns, min_len)
            if new_args != record.args:
                redacted += 1
            record.args = new_args
        # 3. The formatted exception text, if any.
        if getattr(record, "exc_text", None):
            scrubbed, n = redact_string(record.exc_text, self.patterns, min_len)
            if n:
                record.exc_text = scrubbed
                redacted += n
        if redacted:
            record.redacted_count = getattr(record, "redacted_count", 0) + redacted
        return True


# Module-level cache so install_redact_filter() is idempotent.
_INSTALLED: bool = False
_OLD_FACTORY = None  # the LogRecord factory we wrapped, for reset


def install_redact_filter(logger: logging.Logger | None = None, *, patterns=None) -> RedactSecretsFilter:
    """Install RedactSecretsFilter via logging.setLogRecordFactory.

    Why the factory and not logger.addFilter? Python's logger-level
    filters only run when the record originates at that logger.
    Records that propagate from a child logger bypass the parent's
    filter list. The LogRecord factory runs at record *creation*
    time (in LogRecord.__init__), so the redaction is guaranteed
    regardless of which logger issued the call.

    Idempotent: calling this twice returns the same filter instance
    and does not wrap the factory twice.

    Args:
        logger: ignored; kept for backwards compatibility (and to
            mirror the typical "install on a logger" interface).
        patterns: optional extra compiled regex patterns.

    Returns:
        The RedactSecretsFilter instance whose .filter() is invoked
        by the wrapped factory.
    """
    global _INSTALLED, _OLD_FACTORY
    # If a filter is already installed, just return it.
    if _INSTALLED:
        for hdlr in logging.getLogger().handlers:
            pass
        # Find the existing RedactSecretsFilter by inspecting the
        # installed factory closure. Simpler: track on the module.
        return _current_filter()
    flt = RedactSecretsFilter(patterns=patterns if patterns is not None else DEFAULT_PATTERNS)
    old_factory = logging.getLogRecordFactory()
    if getattr(old_factory, "_smolcode_redact_wrapped", False):
        # Already wrapped; do not double-wrap.
        return _current_filter()

    def _factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        flt.filter(record)
        return record

    setattr(_factory, "_smolcode_redact_wrapped", True)
    setattr(_factory, "_smolcode_redact_filter", flt)
    logging.setLogRecordFactory(_factory)
    _OLD_FACTORY = old_factory
    _INSTALLED = True
    return flt


def _current_filter() -> RedactSecretsFilter:
    """Return the RedactSecretsFilter currently in the factory chain."""
    factory = logging.getLogRecordFactory()
    flt = getattr(factory, "_smolcode_redact_filter", None)
    if isinstance(flt, RedactSecretsFilter):
        return flt
    raise RuntimeError("RedactSecretsFilter is not installed")


def is_installed() -> bool:
    """Return True if a RedactSecretsFilter is installed via setLogRecordFactory."""
    return _INSTALLED


def reset_for_tests() -> None:
    """Restore the previous LogRecord factory.

    Test-only helper. Idempotent. Calling this when nothing is
    installed is a no-op.
    """
    global _INSTALLED, _OLD_FACTORY
    if not _INSTALLED:
        return
    if _OLD_FACTORY is not None:
        logging.setLogRecordFactory(_OLD_FACTORY)
    else:
        logging.setLogRecordFactory(logging.LogRecord)
    _OLD_FACTORY = None
    _INSTALLED = False


__all__ = [
    "DEFAULT_PATTERNS",
    "MIN_TOKEN_LEN",
    "RedactSecretsFilter",
    "install_redact_filter",
    "is_installed",
    "redact_string",
    "reset_for_tests",
]


if __name__ == "__main__":  # pragma: no cover
    install_redact_filter()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.info("using key %s", "sk-abcdefghijklmnopqrstuvwxyz0123456789")
    logging.info("anthropic %s", "sk-ant-api03-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKL")
    logging.info("huggingface %s", "hf_abcdefghijklmnopqrstuvwxyz0123456789")
    logging.info("github %s", "ghp_abcdefghijklmnopqrstuvwxyz0123456789")
    logging.info("github oauth %s", "gho_abcdefghijklmnopqrstuvwxyz0123456789")
    logging.info("github user %s", "ghu_abcdefghijklmnopqrstuvwxyz0123456789")
    logging.info("github server %s", "ghs_abcdefghijklmnopqrstuvwxyz0123456789")
    logging.info("google %s", "AIzaSyD-abcdefghijklmnopqrstuvwxyz0123456789")
    logging.info("aws %s", "AKIAIOSFODNN7EXAMPLE")
    logging.info("safe message with no secrets")

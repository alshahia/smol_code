"""Force UTF-8 I/O for the entire process on Windows.

Decision 0024.2: the Web UI runs agent.run inside a worker thread
that inherits the parent process's sys.stdout / sys.stderr. When the
executor (RemotePythonExecutor.install_packages) emits pip progress
output, smolagents' StepLogger.log -> Rich console.print ->
legacy_windows_render tries to encode pip's box-drawing and emoji
characters via the legacy Windows cp1252/cp1256 codec -- which fails
with "UnicodeEncodeError: 'charmap' codec can't encode characters in
position N-M: character maps to <undefined>". The exception bubbles
up through the sandbox guard's send_tools path and aborts the run
before the agent can produce any answer.

We can't fix this by setting env vars after Python has already
initialised the codec, because the legacy Windows renderer captures
self.write = file.write at construction time. Reconfiguring
sys.stdout later does change the codec state, but we ALSO need to make
sure no Rich Console is constructed BEFORE the reconfig, otherwise
its legacy_windows flag will be set against the old (cp1256) file.

So: this module runs from smolcode/__init__.py BEFORE any smolcode
submodule imports smolagents. By the time smolagents constructs its
Rich Console, sys.stdout.encoding is already utf-8 -- which the
Console picks up via its "encoding" property
(getattr(self.file, "encoding", "utf-8")), and which makes
LegacyWindowsTerm(self.file) use UTF-8 when write_text calls
self.write(text).

The function is idempotent (safe to call multiple times) so callers
don't need to coordinate.
"""

from __future__ import annotations

import os
import sys


_DONE = False


def setup_unicode_env():
    """Reconfigure process stdio to UTF-8.

    Idempotent. Safe to call multiple times -- a no-op after the first
    successful run. Errors are swallowed because we never want the
    helper to make things worse (the failure mode we're fixing is
    already pretty bad).
    """
    global _DONE
    if _DONE:
        return
    # 1. Set env vars so subprocesses and lazy codec initialisations
    #    also pick UTF-8.
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    # 2. Reconfigure the streams themselves. reconfigure() mutates
    #    the existing TextIOWrapper in place, so any Rich Console that
    #    captured self.write = file.write before this call will pick
    #    up the new encoding when its write_text method invokes it.
    for stream_name in ("stdout", "stderr", "stdin"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    _DONE = True


__all__ = ["setup_unicode_env"]

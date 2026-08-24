"""smolcode - local/Docker multi-agent coding assistant built on smolagents."""

# Decision 0024.2: reconfigure stdio to UTF-8 BEFORE anything else
# imports. We must do this at the package init so that by the time
# smolagents constructs its Rich Console, sys.stdout.encoding is
# already "utf-8" -- otherwise pip output containing emoji /
# box-drawing characters trips the legacy Windows cp1252/cp1256 codec
# and aborts the run with UnicodeEncodeError. The helper is idempotent.
from ._unicode_env import setup_unicode_env


setup_unicode_env()


__version__ = "0.1.0"

"""SPA bundle freshness helpers (2026-10-24 repair assessment, Step 0.3).

The web server mounts `web/dist` when it exists (server.py). A served
bundle can silently go stale after frontend edits: the operator sees the
old UI while the source tree has moved on. Rather than hiding that, the
server logs a warning at boot (and GET /api/health reports `spa_stale` -
see web/health.py) so "rebuild the SPA" is an actionable message.

Freshness is a pure stat comparison: newest mtime under `web/src`, plus
`package.json` / `vite.config.ts` / `index.html`, versus `dist/index.html`.
A missing bundle is "not stale" (nothing is being served).
"""

from __future__ import annotations

from pathlib import Path


__all__ = ["spa_dir", "spa_is_stale", "spa_src_dir"]

# Tolerate filesystems with coarse mtime granularity and the natural
# write ordering of a build (assets are written before index.html).
_STALE_TOLERANCE_S = 1.0


def spa_dir() -> Path:
    """Return the built bundle directory (`smolcode/web/dist`)."""
    return Path(__file__).resolve().parents[3] / "web" / "dist"


def spa_src_dir() -> Path:
    """Return the frontend source root (`smolcode/web`)."""
    return Path(__file__).resolve().parents[3] / "web"


def spa_is_stale(dist_dir: Path | None = None, src_dir: Path | None = None) -> bool:
    """True when the bundle is older than the frontend sources it was built from.

    Returns False when no `index.html` is present (no bundle is served) and
    when the timestamps are within the tolerance window, so a fresh build is
    never flagged because of coarse timestamp resolution.
    """
    dist = Path(dist_dir) if dist_dir is not None else spa_dir()
    src = Path(src_dir) if src_dir is not None else spa_src_dir()
    index = dist / "index.html"
    if not index.is_file():
        return False
    newest = index.stat().st_mtime
    candidates = (src / "src", src / "package.json", src / "vite.config.ts", src / "index.html")
    for candidate in candidates:
        if candidate.is_file():
            newest = max(newest, candidate.stat().st_mtime)
        elif candidate.is_dir():
            for path in candidate.rglob("*"):
                if path.is_file():
                    newest = max(newest, path.stat().st_mtime)
    return newest > index.stat().st_mtime + _STALE_TOLERANCE_S

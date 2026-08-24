from __future__ import annotations

import logging
from pathlib import Path

from ._models import Specialist, SpecialistError
from .deploy_staging import build_deploy_staging_specialist


_log = logging.getLogger(__name__)


# Default path for user-installed specialists (D10).
USER_SPECIALISTS_PATH = Path.home() / ".smolcode" / "specialists.toml"


def bundled_specialists():
    """Return the always-available (bundled) specialists."""
    return [build_deploy_staging_specialist()]


def load_user_specialists(settings=None):
    """Load user-installed specialists from ~/.smolcode/specialists.toml.

    The file is OPTIONAL: missing or unreadable files produce an empty
    list (logged at DEBUG). Malformed files raise SpecialistError so
    the user can see the problem instead of silently losing specialists.
    """
    # v1: tomllib is the stdlib parser (Python 3.11+). It is only
    # required if the user actually has a specialists.toml file.
    if not USER_SPECIALISTS_PATH.is_file():
        return []
    try:
        import tomllib  # py3.11+ stdlib
    except ImportError:  # pragma: no cover
        _log.warning("tomllib unavailable; cannot read %s", USER_SPECIALISTS_PATH)
        return []
    try:
        with open(USER_SPECIALISTS_PATH, "rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        _log.debug("user specialists file unreadable: %s", e)
        return []
    except Exception as e:
        raise SpecialistError("failed to parse " + str(USER_SPECIALISTS_PATH) + ": " + str(e)) from e
    out = []
    specialists_raw = data.get("specialists") if isinstance(data, dict) else None
    if not isinstance(specialists_raw, list):
        return out
    for entry in specialists_raw:
        if not isinstance(entry, dict):
            continue
        try:
            out.append(
                Specialist(
                    name=str(entry["name"]),
                    tier=str(entry.get("tier", "full_access")),
                    description=str(entry.get("description", "")),
                    tools=tuple(entry.get("tools", []) or []),
                    extra_paths=tuple(entry.get("extra_paths", []) or []),
                )
            )
        except SpecialistError:
            raise
        except Exception as e:
            raise SpecialistError("invalid specialist entry " + repr(entry) + ": " + str(e)) from e
    return out


def resolve_specialist(name, settings=None, specialists=None):
    """Look up one specialist by name. Returns None if not found.

    Combines bundled + user-installed specialists unless an explicit
    list is provided (used by tests).
    """
    if specialists is None:
        specialists = list(bundled_specialists())
        if settings is not None:
            specialists.extend(load_user_specialists(settings))
    for s in specialists:
        if s.name == name:
            return s
    return None


__all__ = [
    "Specialist",
    "SpecialistError",
    "USER_SPECIALISTS_PATH",
    "bundled_specialists",
    "load_user_specialists",
    "resolve_specialist",
]

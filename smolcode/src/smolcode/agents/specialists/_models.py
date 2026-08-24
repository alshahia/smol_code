from __future__ import annotations

from dataclasses import dataclass


class SpecialistError(KeyError):
    """Raised when a specialist name is unknown or its toolset is invalid."""


@dataclass(frozen=True)
class Specialist:
    """A pre-configured sub-agent: a named tier with a narrowed toolset."""

    name: str
    tier: str
    description: str
    tools: tuple[str, ...]
    extra_paths: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.name or not isinstance(self.name, str):
            raise SpecialistError("specialist name must be a non-empty string")
        if self.tier not in ("restricted", "elevated", "full_access"):
            raise SpecialistError("specialist " + repr(self.name) + " has unknown tier " + repr(self.tier))


__all__ = ["Specialist", "SpecialistError"]

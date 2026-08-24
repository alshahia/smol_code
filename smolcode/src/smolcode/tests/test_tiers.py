"""M4 - tier definitions + agent factories."""

import pytest

from smolcode.agents import (
    build_elevated_agent,
    build_full_access_agent,
    build_restricted_agent,
    make_agent,
)
from smolcode.config import Tier, _default_tiers


# ---- Tier dataclass shape (M4) -------------------------------------------


class TestTierShape:
    def test_default_tiers_keys(self):
        ts = _default_tiers()
        assert set(ts.keys()) == {"restricted", "elevated", "full_access"}

    def test_restricted_tier(self):
        t = _default_tiers()["restricted"]
        assert t.name == "restricted"
        assert t.network == "none"
        assert t.network_allowlist == ()
        assert t.max_steps == 12
        assert "json" in t.imports
        assert "git" in t.commands
        assert "ssh" not in t.commands
        assert "docker" not in t.commands

    def test_elevated_tier(self):
        t = _default_tiers()["elevated"]
        assert t.name == "elevated"
        assert t.network == "restricted"
        assert t.network_allowlist == ()
        assert t.max_steps == 20
        assert "collections" in t.imports
        assert "shutil" in t.imports
        assert "pip" in t.commands
        assert "curl" in t.commands
        # Still NOT in elevated.
        assert "ssh" not in t.commands
        assert "docker" not in t.commands
        assert "subprocess" not in t.imports
        assert "socket" not in t.imports

    def test_full_access_tier(self):
        t = _default_tiers()["full_access"]
        assert t.name == "full_access"
        assert t.network == "open"
        assert t.network_allowlist == ("*",)
        assert t.max_steps == 40
        assert "subprocess" in t.imports
        assert "socket" in t.imports
        assert "asyncio" in t.imports
        assert "ssh" in t.commands
        assert "docker" in t.commands
        assert "kubectl" in t.commands
        assert "aws" in t.commands

    def test_tier_dataclass_requires_network_allowlist(self):
        # Constructing Tier without network_allowlist must fail.
        with pytest.raises(TypeError):
            Tier(  # type: ignore[call-arg]
                name="x",
                imports=(),
                commands=(),
                paths=(),
                network="none",
                mcp_servers=(),
                max_steps=1,
                timeout_s=1.0,
                docker_image="x:y",
            )

    def test_tier_equality_includes_network_allowlist(self):
        a = Tier(
            name="x",
            imports=(),
            commands=(),
            paths=(),
            network="none",
            network_allowlist=(),
            mcp_servers=(),
            max_steps=1,
            timeout_s=1.0,
            docker_image="x:y",
        )
        b = Tier(
            name="x",
            imports=(),
            commands=(),
            paths=(),
            network="none",
            network_allowlist=("github.com",),
            mcp_servers=(),
            max_steps=1,
            timeout_s=1.0,
            docker_image="x:y",
        )
        assert a != b  # network_allowlist differs

    def test_tier_imports_are_tuples(self):
        ts = _default_tiers()
        for n in ("restricted", "elevated", "full_access"):
            assert isinstance(ts[n].imports, tuple)
            assert isinstance(ts[n].commands, tuple)
            assert isinstance(ts[n].paths, tuple)
            assert isinstance(ts[n].network_allowlist, tuple)
            assert isinstance(ts[n].mcp_servers, tuple)


# ---- Agent factories exist + dispatch ------------------------------------


class TestAgentFactories:
    def test_factories_importable(self):
        # Just importing them is the test; ensures __init__ exports.
        assert callable(build_restricted_agent)
        assert callable(build_elevated_agent)
        assert callable(build_full_access_agent)
        assert callable(make_agent)

    def test_factories_are_in_smoldcode_agents(self, _isolate_env):
        import smolcode.agents

        assert hasattr(smolcode.agents, "build_restricted_agent")
        assert hasattr(smolcode.agents, "build_elevated_agent")
        assert hasattr(smolcode.agents, "build_full_access_agent")
        assert hasattr(smolcode.agents, "make_agent")

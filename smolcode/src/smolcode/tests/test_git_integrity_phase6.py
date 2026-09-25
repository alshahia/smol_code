"""Docker-executor contract: the hardened git env must survive serialisation.

tools/git.py is serialised into the sandbox by smolagents
(instance_to_source), then rebuilt with get_tools_definition_code and exec-ed.
Every piece of per-build state has to arrive as a CLASS attribute or the
rebuilt tool is dead in the container. This test mirrors that path rather
than trusting the class definition.

This is the test that catches the failure where git_env existed on the
host-side class but no bound tool ever carried it.
"""

from __future__ import annotations

import os

from smolagents import Tool
from smolagents.tools import instance_to_source

from smolcode.tools import CommandPolicy
from smolcode.tools.git import build_git_tools


def _push(**kw):
    opts = {"cwd": os.getcwd(), "tier_name": "restricted"}
    opts.update(kw)
    return [t for t in build_git_tools(CommandPolicy(("git",)), **opts) if t.name == "git_push"][0]


class TestHardenedEnvSurvivesSerialisation:
    def test_serialised_source_carries_git_env(self):
        src = instance_to_source(_push(), base_cls=Tool)
        assert "git_env" in src

    def test_the_rebuilt_definition_carries_the_hardening(self):
        from smolagents.tools import get_tools_definition_code

        tool = _push()
        code = get_tools_definition_code({tool.name: tool})
        assert "GIT_CONFIG_NOSYSTEM" in code
        assert "GIT_CONFIG_GLOBAL" in code

    def test_no_built_tool_falls_back_to_the_host_environment(self):
        for tool in build_git_tools(CommandPolicy(("git",)), cwd=os.getcwd(), tier_name="elevated"):
            env = tool.git_env
            assert env is not None, tool.name
            assert env.get("GIT_CONFIG_NOSYSTEM") == "1", tool.name

    def test_validation_survives_serialisation(self):
        src = instance_to_source(_push(), base_cls=Tool)
        assert "core.hooksPath=" in src
        assert "not configured in this repository" in src

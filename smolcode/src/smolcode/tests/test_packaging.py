"""Phase 3 (decision 0038, review R1): packaging contract for the wheel.

The 2026-09-24 review installed a freshly built wheel into a clean venv and
got: ``ImageBuildError: build input missing: .../docker/restricted.Dockerfile``.
``pyproject.toml`` declared ``[tool.setuptools.packages.find] where=["src"]``
but no package-data, so the tier build context (``docker/*.Dockerfile`` +
``iptables-init.sh``) never made it into the distribution. These tests pin
the contract:

* the build context resolves next to the installed package and contains
  every file ``images._context_files`` asks for;
* ``source_hash`` is a stable 64-hex digest per tier (no Docker needed);
* a Docker client that cannot be constructed surfaces as ``ImageBuildError``
  (one-line message + CLI exit code 6), not a raw ``DockerException``
  traceback;
* the project metadata the packaging job relies on is present.

These tests import from the source tree. The authoritative proof that the
files are in the wheel is the CI ``packaging`` job, which installs the
built wheel into a throwaway venv and runs ``images hash restricted``.
"""

import re
from pathlib import Path

import pytest
import tomllib

from smolcode import images


_PYPROJECT = Path(__file__).resolve().parents[3] / "pyproject.toml"
_TIERS = ("restricted", "elevated", "full_access")


@pytest.mark.parametrize("tier", _TIERS)
def test_build_context_exists_in_source_tree(tier):
    ctx = images.tier_build_context()
    assert ctx.is_dir(), f"build context missing: {ctx}"
    for name in images._context_files(tier):
        assert (ctx / name).is_file(), f"{tier} build input missing from context: {name}"


@pytest.mark.parametrize("tier", _TIERS)
def test_source_hash_is_stable_64_hex(tier):
    first = images.source_hash(tier)
    second = images.source_hash(tier)
    assert first == second
    assert re.fullmatch(r"[0-9a-f]{64}", first), first


def test_source_hash_elevated_differs_from_restricted():
    # elevated COPYs iptables-init.sh, restricted does not -- if these
    # collide the label check would treat the wrong image as current.
    assert images.source_hash("elevated") != images.source_hash("restricted")


def test_source_hash_unknown_tier_raises_image_build_error():
    with pytest.raises(images.ImageBuildError):
        images.source_hash("nonexistent")


def test_get_client_wraps_docker_construction_failure():
    """A missing daemon must be an ImageBuildError, not a raw traceback."""

    def _from_env():
        raise RuntimeError("docker pipe missing")

    import docker  # real module; only the factory is replaced

    original = docker.from_env
    docker.from_env = _from_env
    try:
        with pytest.raises(images.ImageBuildError) as exc:
            images._get_client()
    finally:
        docker.from_env = original
    assert "docker" in str(exc.value).lower()


def test_pyproject_declares_package_data_for_docker_context():
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    package_data = data.get("tool", {}).get("setuptools", {}).get("package-data", {})
    patterns = package_data.get("smolcode", [])
    assert any(p.startswith("docker/") for p in patterns), package_data


def test_pyproject_metadata_for_release():
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    project = data["project"]
    assert project["name"] == "smolcode"
    assert re.fullmatch(r"\d+\.\d+\.\d+", project["version"]), project["version"]
    assert project["scripts"]["smolcode"] == "smolcode.cli:main"

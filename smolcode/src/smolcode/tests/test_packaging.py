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
import shutil
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


# ---- Phase 8 (decision 0043): publishable metadata + digest pins ----------


def test_pyproject_has_pypi_readme_urls_and_classifiers():
    project = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]
    # The long description is the file next to pyproject.toml; a missing
    # readme makes `uv build` fail, which is why this is asserted.
    assert project["readme"] == "README.md"
    assert (Path(__file__).resolve().parents[3] / "README.md").is_file()

    urls = project["urls"]
    assert urls["Homepage"] == "https://github.com/alshahia/smol_code"
    assert urls["Repository"] == "https://github.com/alshahia/smol_code"
    assert urls["Issues"].endswith("/issues")

    classifiers = project["classifiers"]
    for minor in ("3.10", "3.11", "3.12", "3.13"):
        assert "Programming Language :: Python :: " + minor in classifiers
    assert "Operating System :: OS Independent" in classifiers
    assert "Environment :: Console" in classifiers
    assert any(c.startswith("Topic ::") for c in classifiers)
    assert project["keywords"]

    # Deliberately NOT invented: the repo has no license/authors.
    assert "license" not in project
    assert "authors" not in project


def test_package_data_includes_every_docker_build_input():
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    patterns = data["tool"]["setuptools"]["package-data"]["smolcode"]
    for tier in _TIERS:
        for name in images._context_files(tier):
            assert "docker/" + name in patterns, name
    # The host image's Dockerfile ships too, so a wheel install can build it
    # from the repo without a checkout of this phase.
    assert "docker/Dockerfile.host" in patterns


@pytest.mark.parametrize("tier", _TIERS)
def test_tier_dockerfiles_pin_base_image_by_digest(tier):
    digest = images.base_image_digest(tier)
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest), digest
    # The digest must be the one the FROM resolves to (ARG default form).
    dockerfile = images.tier_build_context() / images._tier_dockerfile(tier, images.tier_build_context())
    assert digest in dockerfile.read_text(encoding="utf-8")


def test_host_dockerfile_is_hardened_and_digest_pinned():
    text = (images.tier_build_context() / "Dockerfile.host").read_text(encoding="utf-8")
    assert re.search(r"^FROM python:3\.12-slim@sha256:[0-9a-f]{64}", text, re.MULTILINE)
    assert "EXPOSE 7860" in text
    assert "STOPSIGNAL SIGTERM" in text
    assert "HEALTHCHECK" in text and "/api/health" in text
    assert "USER 10001:10001" in text
    assert 'ENTRYPOINT ["smolcode", "web", "--no-browser"]' in text
    assert "org.opencontainers.image.source" in text


def _scratch_context(tmp_path, tier):
    ctx = tmp_path / "docker"
    ctx.mkdir()
    for name in images._context_files(tier):
        shutil.copy(images.tier_build_context() / name, ctx / name)
    return ctx


def test_source_hash_changes_when_base_digest_changes(tmp_path):
    tier = "restricted"
    ctx = _scratch_context(tmp_path, tier)
    baseline = images.source_hash(tier)
    assert images.source_hash(tier, ctx) == baseline

    dockerfile = ctx / images._tier_dockerfile(tier, ctx)
    old_digest = images.base_image_digest(tier, ctx)
    new_digest = "sha256:" + "ab" * 32
    dockerfile.write_text(dockerfile.read_text(encoding="utf-8").replace(old_digest, new_digest), encoding="utf-8")

    assert images.base_image_digest(tier, ctx) == new_digest
    assert images.source_hash(tier, ctx) != baseline, "a changed base digest must invalidate the image"


def test_tag_only_base_is_rejected(tmp_path):
    tier = "restricted"
    ctx = _scratch_context(tmp_path, tier)
    dockerfile = ctx / images._tier_dockerfile(tier, ctx)
    text = re.sub(r"sha256:[0-9a-f]{64}", "", dockerfile.read_text(encoding="utf-8"))
    dockerfile.write_text(text, encoding="utf-8")
    with pytest.raises(images.ImageBuildError, match="digest"):
        images.base_image_digest(tier, ctx)
    with pytest.raises(images.ImageBuildError, match="digest"):
        images.source_hash(tier, ctx)

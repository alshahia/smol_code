"""Phase 3 (decision 0038, review R5): test-environment isolation.

These tests pin the two properties that made the suite unrunnable on a
Docker-less machine:

1. the autouse fixture defaults SMOLCODE_EXECUTOR to local, so a
   TestClient(app) boot cannot try to build tier images;
2. the docker_executor fixture flips it back for the tests that opt in.

The end-to-end proof (a TestClient boot that used to raise
docker.errors.DockerException) is any of the existing web API test
modules; this file pins the mechanism so the default cannot silently
regress.
"""

import os

import pytest


def test_isolate_env_defaults_executor_to_local():
    # The autouse _isolate_env fixture has already run for this test.
    assert os.environ.get("SMOLCODE_EXECUTOR") == "local"


def test_isolate_env_still_clears_other_settings():
    # Guard the original responsibility: the fixture must not stop
    # clearing SMOLCODE_* vars just because it now sets one of them.
    assert os.environ.get("SMOLCODE_WORKSPACE")
    assert os.environ.get("SMOLCODE_AUDIT_LOG")


def test_docker_executor_fixture_opts_back_in(docker_executor):
    assert docker_executor == "docker"
    assert os.environ.get("SMOLCODE_EXECUTOR") == "docker"


def test_docker_executor_is_not_autouse():
    # Without the fixture the autouse default must still be in force,
    # otherwise docker_executor would leak into every test.
    assert os.environ.get("SMOLCODE_EXECUTOR") == "local"


@pytest.mark.docker
def test_docker_executor_fixture_is_usable_with_docker_marker(docker_executor):
    # This test is deselected by -m 'not docker'; it only asserts the
    # fixture is importable and flips the env var, never touches Docker.
    assert os.environ.get("SMOLCODE_EXECUTOR") == "docker"

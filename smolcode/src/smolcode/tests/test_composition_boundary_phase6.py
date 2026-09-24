"""Phase 6 section 6.3 -- the composition boundary at the mount layer.

R9: every tier received the SAME rw bind mount of the whole workspace, so a
restricted container could rewrite the uploads directory even though the
tier policy declares uploads read-only there. Policy enforced only in the
tool layer is policy the model can route around; this moves the boundary
into Docker itself.

No Docker daemon is needed: _executor_kwargs_for is a pure function that
returns the kwargs dict.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from smolcode.agents.base import _CONTAINER_WORKSPACE, _executor_kwargs_for
from smolcode.config import load_settings


@pytest.fixture
def ws(tmp_path, monkeypatch):
    d = tmp_path / "ws"
    (d / ".smolcode" / "uploads").mkdir(parents=True)
    monkeypatch.setenv("SMOLCODE_WORKSPACE", str(d))
    monkeypatch.setenv("SMOLCODE_UPLOAD_DIR", str(d / ".smolcode" / "uploads"))
    return d


def _vols(tier_name, ws):
    s = load_settings()
    kwargs = _executor_kwargs_for("docker", s.tiers[tier_name], s)
    return kwargs["container_run_kwargs"]["volumes"]


def test_restricted_gets_a_read_only_uploads_mount(ws):
    vols = _vols("restricted", ws)
    ro = [(k, v) for k, v in vols.items() if v["mode"] == "ro"]
    assert ro, "restricted tier has no read-only mount; uploads remain writable"
    host_path, spec = ro[0]
    assert Path(host_path) == Path(ws / ".smolcode" / "uploads").resolve()
    assert spec["bind"].startswith(_CONTAINER_WORKSPACE)


def test_the_workspace_itself_stays_read_write(ws):
    # The point is a NARROWER boundary, not an unusable tier: the restricted
    # agent must still be able to edit the code it was asked to.
    vols = _vols("restricted", ws)
    assert vols[str(ws)]["mode"] == "rw"


def test_elevated_is_unaffected(ws):
    # elevated is allowed to write uploads, so it must NOT get the ro mount.
    vols = _vols("elevated", ws)
    assert not [1 for v in vols.values() if v["mode"] == "ro"]


def test_uploads_outside_the_workspace_are_left_alone(tmp_path, monkeypatch):
    # Mounting a path the container was never given would silently change
    # where uploads appear, so an out-of-tree uploads_dir is skipped and the
    # tool-layer policy remains the boundary.
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "elsewhere" / "uploads"
    outside.mkdir(parents=True)
    monkeypatch.setenv("SMOLCODE_WORKSPACE", str(ws))
    monkeypatch.setenv("SMOLCODE_UPLOAD_DIR", str(outside))
    vols = _vols("restricted", ws)
    assert str(ws) in vols
    assert not [1 for v in vols.values() if v["mode"] == "ro"]

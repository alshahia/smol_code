"""Phase 3 RED tests for F3 (project-root anchoring + outside-root policy).

Bug surface:
    - Run has no effective_cwd / anchor_to_project_root fields. The
      agent's write_file/patch_file always resolve relative paths
      against settings.workspace, ignoring the selected project.
      Confirmed on the live pwsh-2 server with project="1" anchored
      conceptually: the agent wrote .web-ws/todo_app/* even though
      .web-ws/1/ existed.
    - _rel_path anchors against run.workspace only; it does not consult
      effective_cwd. So "anchored" writes land on ../todo_app/x.py when
      the user expects todo_app/x.py.
    - _build_diff_callback always opens PendingDecision(kind="diff"),
      regardless of whether the path escapes effective_cwd. F3 Q2 says
      BLOCK + full-path modal + per-session per-path allowlist
      (POLICY-DECISIONS.md). This requires:
          - SessionState.outside_root_allowlist: set[str] (new field)
          - PendingDecision(kind="outside_root") (new kind value)
          - PermissionError on the agent's write when denied.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace


class TestEffectiveCwdField:
    """F3 - RED: Run carries effective_cwd + anchor_to_project_root."""

    def test_run_has_effective_cwd_field(self):
        """RED today: Run has no effective_cwd field (Phase 3 adds it
        so the runner can thread it into LocalExecutor(cwd=...) /
        DockerExecutor(work_dir=...))."""
        from smolcode.web.runs import Run

        r = Run(id="phase3-f3-field", task="x", tier="restricted")
        assert hasattr(r, "effective_cwd"), "Run dataclass must carry an 'effective_cwd' attribute (Phase 3 F3)."

    def test_run_has_anchor_to_project_root_field_with_off_default(self):
        """RED today: no per-run toggle. Per Q1 policy the default
        must be False (no behavior change for users who never tick
        the composer checkbox)."""
        from smolcode.web.runs import Run

        r = Run(id="phase3-f3-toggle", task="x", tier="restricted")
        assert hasattr(r, "anchor_to_project_root"), (
            "Run dataclass must carry 'anchor_to_project_root' (Phase 3 F3 + Q1)."
        )
        assert getattr(r, "anchor_to_project_root", None) is False, (
            "anchor_to_project_root default must be False (Q1: off per-run)."
        )


class TestRelativePathAnchor:
    """F3 - RED: _rel_path uses effective_cwd when set + matching."""

    def test_rel_path_anchors_against_effective_cwd(self):
        """RED today: _rel_path anchors against run.workspace only.
        With F3, an anchored run landed at /ws/1/todo_app/x.py must
        yield 'todo_app/x.py' (NOT '../todo_app/x.py' or
        '1/todo_app/x.py')."""
        from smolcode.web.agent_runner import _rel_path

        run = SimpleNamespace(workspace="/ws", effective_cwd="/ws/1")
        out = _rel_path(run, "/ws/1/todo_app/x.py")
        assert out == "todo_app/x.py", (
            "Anchored run landed at /ws/1/todo_app/x.py but _rel_path returned "
            + repr(out)
            + "; effective_cwd=/ws/1 must be the anchor when set."
        )

    def test_rel_path_falls_back_to_workspace_when_effective_cwd_unset(self):
        """Characterization: when effective_cwd is None / equal to
        workspace, _rel_path behaves as before (workspace-relative).
        Today and after Phase 3."""
        from smolcode.web.agent_runner import _rel_path

        # effective_cwd=None is the legacy / no-anchor path.
        run = SimpleNamespace(workspace="/ws", effective_cwd=None)
        out = _rel_path(run, "/ws/todo_app/x.py")
        assert out == "todo_app/x.py", (
            "Legacy path: with effective_cwd=None, _rel_path should yield workspace-relative 'todo_app/x.py'; got "
            + repr(out)
        )


class TestOutsideRootPolicy:
    """F3 - RED: writes that escape effective_cwd hit the Q2 gate."""

    def test_session_state_carries_outside_root_allowlist(self):
        """RED today: SessionState has no outside_root_allowlist. Phase 3
        adds it so the diff callback can skip the modal on repeated writes
        to the same absolute target within one run (per-session per-path
        allowlist per Q2)."""
        from smolcode.session import SessionState

        s = SessionState()
        assert hasattr(s, "outside_root_allowlist"), (
            "SessionState must carry outside_root_allowlist (Phase 3 Q2 allowlist)."
        )
        # Allowlist defaults to an empty set on every new SessionState.
        assert set(getattr(s, "outside_root_allowlist", None) or ()) == set()

    def _minimal_run(self):
        """A SimpleNamespace that fakes just enough of Run for
        _build_diff_callback + open_decision."""
        return SimpleNamespace(
            id="phase3-f3-or-1",
            tier="restricted",
            status="running",
            pending=[],
            pending_lock=threading.Lock(),
            stop_flag=threading.Event(),
            audit_sink=None,
            publish=lambda *_a, **_kw: None,
            effective_cwd="/ws/1",
            anchor_to_project_root=True,
            workspace="/ws",
            touched_paths=set(),
            touched_lock=threading.Lock(),
            session_id=None,
            project="1",
            open_decision=lambda **_kwargs: _install_pending(_kwargs),
        )

    def test_pending_decision_supports_outside_root_kind(self):
        """RED today (as a contract test, GREEN after Phase 3 wires the gate).

        Phase 3 must wire _build_diff_callback to open a
        PendingDecision(kind='outside_root') for writes that escape
        effective_cwd. The dataclass is free-form today (kind=str), so
        the test is structural: confirm the kind string and path are
        preserved through construction; the BEHAVIORAL test of the
        callback itself is added in Phase 3 Task 5.
        """
        from smolcode.web.runs import PendingDecision

        d = PendingDecision(
            id="phase3-f3-outside-root-1",
            tool="write_file",
            args={},
            summary="outside-root test",
            tier="restricted",
            kind="outside_root",
            path="C:/tmp/outside.txt",
        )
        assert d.kind == "outside_root"
        assert d.path.endswith("outside.txt")


def _install_pending(kwargs):
    """Used by self._minimal_run() when no override is supplied."""
    return SimpleNamespace(
        id="d-default",
        kind=kwargs.get("kind", "diff"),
        path=str(kwargs.get("path", "")),
        args=kwargs.get("args", {}),
        summary=kwargs.get("summary", ""),
        tool=kwargs.get("tool", ""),
        event=SimpleNamespace(wait=lambda timeout=5: True),
        resolve=lambda *_a, **_kw: None,
    )

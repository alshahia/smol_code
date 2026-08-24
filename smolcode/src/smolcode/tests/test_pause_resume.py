"""Tests for Phase 2 (decision 0025 §6.4): pause / resume + snapshot.

These tests exercise the Run / RunManager pause/resume contract WITHOUT
spinning up a real agent (no smolagents network or Docker). The agent
runner integration is covered by test_agent_runner_pause.py separately.

Scenarios:

1. ``Run.pause_flag`` defaults to unset and can be set externally.
2. ``Run.snapshot()`` captures ``agent.memory`` (mock agent) to a JSON
   dict + ``Run.snapshot_path``.
3. ``Run.load_snapshot(path)`` parses a snapshot JSON back into a dict
   usable by ``_resume_agent_from_snapshot``.
4. ``RunManager.enqueue(run_id)`` appends to ``RunManager._queue``; the
   dequeue returns FIFO order.
5. ``STATUS_PAUSED`` is NOT a terminal status (resumable).
6. ``Run.subagent_history`` accumulates entries (Phase 0 §14.8 #3
   fold-in); the legacy single-invocation ``subagent`` accessor returns
   the latest entry.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from typing import List

from smolcode.web.runs import (
    _TERMINAL_STATUSES,
    STATUS_DONE,
    STATUS_PAUSED,
    STATUS_STOPPED,
    Run,
    RunManager,
)


# ---- helpers --------------------------------------------------------------
#
# Each test fake is named EXACTLY like the smolagents class it stands
# in for so ``type(step).__name__`` (the discriminator the Run.snapshot
# implementation uses) produces the expected value without monkey
# patching.


@dataclass
class TaskStep:
    task: str = ""
    task_images: list | None = None

    def dict(self):
        return {"task": self.task, "task_images": self.task_images}


@dataclass
class ActionStep:
    step_number: int = 0
    text: str = ""

    def dict(self):
        return {"step_number": self.step_number, "text": self.text}


@dataclass
class PlanningStep:
    plan: str = ""

    def dict(self):
        return {"plan": self.plan}


@dataclass
class _FakeMemory:
    system_prompt: str
    steps: List = field(default_factory=list)


@dataclass
class _FakeAgent:
    memory: _FakeMemory


def _make_run_with_fake_agent(task: str = "do something") -> tuple:
    run = Run(id="r" + os.urandom(3).hex(), task=task, tier="restricted")
    agent = _FakeAgent(
        memory=_FakeMemory(
            system_prompt="you are an agent",
            steps=[
                TaskStep(task=task),
                ActionStep(step_number=1, text="think"),
                ActionStep(step_number=2, text="act"),
            ],
        )
    )
    return run, agent


# ---- TestPauseFlag --------------------------------------------------------


class TestPauseFlag:
    def test_pause_flag_defaults_unset(self):
        run = Run(id="r1", task="t", tier="restricted")
        assert isinstance(run.pause_flag, threading.Event)
        assert run.pause_flag.is_set() is False

    def test_pause_flag_can_be_set_externally(self):
        run = Run(id="r1", task="t", tier="restricted")
        run.pause_flag.set()
        assert run.pause_flag.is_set() is True

    def test_pause_flag_clearable(self):
        run = Run(id="r1", task="t", tier="restricted")
        run.pause_flag.set()
        run.pause_flag.clear()
        assert run.pause_flag.is_set() is False


# ---- TestStatusPaused -----------------------------------------------------


class TestStatusPaused:
    def test_status_paused_constant(self):
        assert STATUS_PAUSED == "paused"

    def test_paused_is_not_terminal(self):
        """A paused run is resumable, so it is NOT a terminal status."""
        assert STATUS_PAUSED not in _TERMINAL_STATUSES
        for s in (STATUS_DONE, "error", STATUS_STOPPED):
            assert s in _TERMINAL_STATUSES

    def test_paused_can_be_set_on_run(self):
        run = Run(id="r1", task="t", tier="restricted")
        run.status = STATUS_PAUSED
        assert run.status == STATUS_PAUSED


# ---- TestSnapshot ---------------------------------------------------------


class TestSnapshot:
    def test_snapshot_captures_memory_to_path(self, tmp_path):
        run, agent = _make_run_with_fake_agent()
        out = run.snapshot(agent, path=tmp_path / "snap.json")
        assert out == tmp_path / "snap.json"
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["system_prompt"] == "you are an agent"
        assert len(data["steps"]) == 3
        kinds = [s["step_type"] for s in data["steps"]]
        assert kinds == ["TaskStep", "ActionStep", "ActionStep"]

    def test_snapshot_records_timestamp(self, tmp_path):
        run, agent = _make_run_with_fake_agent()
        path = tmp_path / "snap.json"
        run.snapshot(agent, path=path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data.get("captured_at"), (int, float))
        assert data["captured_at"] > 0

    def test_load_snapshot_roundtrip(self, tmp_path):
        run, agent = _make_run_with_fake_agent()
        path = tmp_path / "snap.json"
        run.snapshot(agent, path=path)
        loaded = run.load_snapshot(path)
        assert loaded["system_prompt"] == "you are an agent"
        assert [s["step_type"] for s in loaded["steps"]] == [
            "TaskStep",
            "ActionStep",
            "ActionStep",
        ]
        assert loaded["steps"][1]["step_number"] == 1
        assert loaded["steps"][2]["text"] == "act"

    def test_snapshot_path_attribute(self, tmp_path):
        run, agent = _make_run_with_fake_agent()
        run.snapshot(agent, path=tmp_path / "snap.json")
        assert str(run.snapshot_path).endswith("snap.json")
        assert run.snapshot_at is not None
        assert run.snapshot_at > 0


# ---- TestQueue ------------------------------------------------------------


class TestQueue:
    def test_enqueue_appends_to_queue(self):
        rm = RunManager()
        rm.enqueue("a", task="t1", tier="restricted")
        rm.enqueue("b", task="t2", tier="restricted")
        assert [e.id for e in rm.queue()] == ["a", "b"]

    def test_dequeue_returns_fifo(self):
        rm = RunManager()
        rm.enqueue("a", task="t1", tier="restricted")
        rm.enqueue("b", task="t2", tier="restricted")
        rm.enqueue("c", task="t3", tier="restricted")
        first = rm.dequeue()
        second = rm.dequeue()
        assert first.id == "a"
        assert second.id == "b"

    def test_dequeue_empty_returns_none(self):
        rm = RunManager()
        assert rm.dequeue() is None

    def test_cancel_queue_entry(self):
        rm = RunManager()
        rm.enqueue("a", task="t1", tier="restricted")
        rm.enqueue("b", task="t2", tier="restricted")
        rm.enqueue("c", task="t3", tier="restricted")
        removed = rm.cancel_queue("b")
        assert removed is True
        assert [e.id for e in rm.queue()] == ["a", "c"]

    def test_cancel_unknown_returns_false(self):
        rm = RunManager()
        rm.enqueue("a", task="t1", tier="restricted")
        assert rm.cancel_queue("missing") is False


# ---- TestSubAgentHistory --------------------------------------------------


class TestSubAgentHistory:
    """Phase 0 §14.8 #3 fold-in: track ALL sub-agent invocations."""

    def test_subagent_history_starts_empty(self):
        run = Run(id="r1", task="t", tier="orchestrator")
        assert run.subagent_history == []

    def test_append_subagent_then_close(self):
        run = Run(id="r1", task="t", tier="orchestrator")
        run.append_subagent("s1", tier="restricted")
        run.append_subagent("s2", tier="elevated")
        assert [s.id for s in run.subagent_history] == ["s1", "s2"]
        run.close_subagent("s1", ended_at=200.0)
        s1 = next(s for s in run.subagent_history if s.id == "s1")
        assert s1.ended_at == 200.0
        s2 = next(s for s in run.subagent_history if s.id == "s2")
        assert s2.ended_at is None

    def test_latest_subagent_property(self):
        """Legacy FE accessor: ``run.subagent`` returns the latest entry."""
        run = Run(id="r1", task="t", tier="orchestrator")
        assert run.subagent is None
        run.append_subagent("s1", tier="restricted")
        assert run.subagent is not None
        assert run.subagent.id == "s1"
        run.append_subagent("s2", tier="elevated")
        assert run.subagent.id == "s2"

    def test_close_unknown_subagent_no_error(self):
        run = Run(id="r1", task="t", tier="orchestrator")
        run.close_subagent("missing", ended_at=100.0)
        assert run.subagent_history == []

    def test_summary_dict_includes_subagent_history(self):
        run = Run(id="r1", task="t", tier="orchestrator")
        run.append_subagent("s1", tier="restricted")
        run.append_subagent("s2", tier="elevated")
        snap = run.summary_dict()
        assert "subagent_history" in snap
        ids = [s["id"] for s in snap["subagent_history"]]
        assert ids == ["s1", "s2"]

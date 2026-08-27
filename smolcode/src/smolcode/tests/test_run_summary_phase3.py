"""Phase 3 RED tests for F2 (Inspector wire shape).

Bug surface:
    web/api.py:_run_summary returns a RunSummary object that omits every
    field the Inspector needs:
        - model (the run's model id)
        - provider (the run's provider)
        - context_window (model's max context, in tokens)
        - context_used (tokens currently consumed by the agent's memory)
        - context_breakdown (system / tools / skills / messages split)
        - tokens.cache_hit (cumulative cache tokens for the session)
        - tokens.current_input / current_output / last_step_at
          (this-step split vs session-total)

    Today the SPy's Inspector.tsx renders only input / output / total /
    step_count and has no source of truth for model, cache, or context
    window. These tests fail today (RED); they pass after Phase 2 lands
    the schema + summary + UI work.
"""

from __future__ import annotations

import time
from types import SimpleNamespace


def _fake_summary_dict(tokens_in=100, tokens_out=50, step_count=1):
    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_total": tokens_in + tokens_out,
        "step_count": step_count,
        "subagent_history": [],
        "snapshot_at": None,
        "queue_position": None,
        "remaining_s": 0.0,
        "subagent": None,
    }


def _fake_run(*, model="deepseek-v4-flash", provider="opencode-go", tokens_in=100, tokens_out=50):
    """A minimal stand-in for a real Run that _run_summary inspects."""
    return SimpleNamespace(
        id="phase3-f2-1",
        task="x",
        tier="restricted",
        status="done",
        started_at=time.time(),
        ended_at=time.time() + 1,
        pending=[],
        session_id=None,
        project=None,
        model=model,
        provider=provider,
        workspace="",
        tokens=None,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        step_count=1,
        snapshot_at=None,
        queue_position=None,
        subagent_history=[],
        result=None,
        error=None,
        touched_list=lambda: [],
        summary_dict=lambda max_wall_s=900: _fake_summary_dict(tokens_in, tokens_out),
    )


class TestRunSummaryNewFields:
    """F2 - RED: _run_summary must propagate model/provider/context/
    cache_hit/current_input/current_output onto the wire."""

    def test_run_summary_contains_model_and_provider(self):
        from smolcode.web.api import _run_summary

        out = _run_summary(_fake_run(model="deepseek-v4-flash", provider="opencode-go"))
        # RED today: RunSummary lacks 'model' / 'provider' fields; the
        # returned dict (RunSummary.model_dump()) does not carry them.
        assert out.get("model") == "deepseek-v4-flash", (
            "RunSummary missing 'model' field (F2 Inspector can't show model id): " + repr(sorted(out.keys()))
        )
        assert out.get("provider") == "opencode-go", (
            "RunSummary missing 'provider' field (F2 Inspector can't show provider): " + repr(sorted(out.keys()))
        )

    def test_run_summary_contains_context_window(self):
        from smolcode.web.api import _run_summary

        out = _run_summary(_fake_run())
        # RED today: context_window is undefined; the Inspector context
        # circle has no denominator.
        assert out.get("context_window") == 128000, (
            "RunSummary missing 'context_window' field (F2 context circle): " + repr(sorted(out.keys()))
        )

    def test_run_summary_tokens_contain_cache_hit(self):
        from smolcode.web.api import _run_summary

        out = _run_summary(_fake_run())
        tokens = out.get("tokens", {})
        assert "cache_hit" in tokens, (
            "TokenSummary missing 'cache_hit' field (F2 Inspector can't show cache): " + repr(sorted(tokens.keys()))
        )

    def test_run_summary_tokens_contain_current_input_and_current_output(self):
        from smolcode.web.api import _run_summary

        out = _run_summary(_fake_run())
        tokens = out.get("tokens", {})
        for k in ("current_input", "current_output"):
            assert k in tokens, (
                "TokenSummary missing '" + k + "' field (F2 Inspector per-step split): " + repr(sorted(tokens.keys()))
            )

    def test_run_summary_tokens_contain_last_step_at(self):
        from smolcode.web.api import _run_summary

        out = _run_summary(_fake_run())
        tokens = out.get("tokens", {})
        assert "last_step_at" in tokens, (
            "TokenSummary missing 'last_step_at' field (F2 Inspector per-step timestamp): "
            + repr(sorted(tokens.keys()))
        )

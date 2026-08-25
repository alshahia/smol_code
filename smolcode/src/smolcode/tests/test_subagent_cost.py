"""Decision 0028 (per-sub-agent cost aggregation) -- BE unit tests.

These tests exercise Run / SubAgentSummary directly (no agent
loop, no FastAPI) to verify:
- Run.append_subagent sets active_subagent_id.
- Run.close_subagent clears active_subagent_id when the closing
  sub-agent is the active one; preserves it when a nested
  sub-agent has already taken over (active_id was overwritten).
- Run.publish with step.action attributes tokens to the active
  sub-agent AND keeps incrementing the outer accumulators.
- Run.publish with NO active sub-agent increments only outer
  accumulators.
- Run.summary_dict emits tokens_in / tokens_out / cost_usd per
  sub-agent using the outer's provider/model.
- Concurrent publish calls do not lose increments.
- specialist is included in the wire (gap fix).
"""

from __future__ import annotations

import threading

from smolcode.web.runs import (
    EVT_STEP_ACTION,
    EVT_SUBAGENT_ENDED,
    EVT_SUBAGENT_STARTED,
    Run,
    SubAgentSummary,
)


def _run(*, provider="openai", model="gpt-4o"):
    r = Run(id="r1", task="t", tier="orchestrator")
    r.provider = provider
    r.model = model
    return r


class TestSubAgentTokenAttribution:
    def test_no_active_subagent_attributes_only_to_outer(self):
        r = _run()
        for inp, out in [(100, 50), (200, 80), (50, 30)]:
            r.publish(EVT_STEP_ACTION, {"tokens": {"input": inp, "output": out}})
        assert r.tokens_in == 350
        assert r.tokens_out == 160
        assert r.step_count == 3
        assert r.subagent_history == []
        assert r.active_subagent_id is None

    def test_active_subagent_attributes_tokens_to_both(self):
        r = _run()
        r.append_subagent("sa1", tier="restricted")
        assert r.active_subagent_id == "sa1"
        r.publish(EVT_STEP_ACTION, {"tokens": {"input": 100, "output": 50}})
        r.publish(EVT_STEP_ACTION, {"tokens": {"input": 200, "output": 80}})
        assert r.tokens_in == 300
        assert r.tokens_out == 130
        sa = r.subagent_history[0]
        assert sa.tokens_in == 300
        assert sa.tokens_out == 130
        assert sa.id == "sa1"
        assert sa.tier == "restricted"

    def test_close_subagent_clears_active_id(self):
        r = _run()
        r.append_subagent("sa1", tier="restricted")
        assert r.active_subagent_id == "sa1"
        r.publish(EVT_STEP_ACTION, {"tokens": {"input": 10, "output": 5}})
        r.close_subagent("sa1")
        assert r.active_subagent_id is None
        r.publish(EVT_STEP_ACTION, {"tokens": {"input": 7, "output": 3}})
        assert r.tokens_in == 17
        assert r.tokens_out == 8
        sa = r.subagent_history[0]
        assert sa.tokens_in == 10
        assert sa.tokens_out == 5
        assert sa.ended_at is not None

    def test_nested_subagent_active_id_overwrites(self):
        r = _run()
        r.append_subagent("sa1", tier="restricted")
        assert r.active_subagent_id == "sa1"
        r.publish(EVT_STEP_ACTION, {"tokens": {"input": 100, "output": 50}})
        r.append_subagent("sa2", tier="elevated")
        assert r.active_subagent_id == "sa2"
        r.publish(EVT_STEP_ACTION, {"tokens": {"input": 10, "output": 5}})
        r.close_subagent("sa1")
        assert r.active_subagent_id == "sa2"
        r.close_subagent("sa2")
        assert r.active_subagent_id is None
        assert r.subagent_history[0].tokens_in == 100
        assert r.subagent_history[0].tokens_out == 50
        assert r.subagent_history[1].tokens_in == 10
        assert r.subagent_history[1].tokens_out == 5
        assert r.tokens_in == 110
        assert r.tokens_out == 55

    def test_close_unknown_subagent_is_noop(self):
        r = _run()
        r.append_subagent("sa1", tier="restricted")
        assert r.close_subagent("sa-unknown") is False
        assert r.active_subagent_id == "sa1"

    def test_append_duplicate_id_does_not_reset_active(self):
        r = _run()
        entry = r.append_subagent("sa1", tier="restricted")
        assert entry is not None
        assert r.active_subagent_id == "sa1"
        again = r.append_subagent("sa1", tier="restricted")
        assert again.id == "sa1"
        assert len(r.subagent_history) == 1
        assert r.active_subagent_id == "sa1"


class TestSubAgentSummaryWire:
    def test_summary_dict_includes_per_subagent_tokens(self):
        r = _run(provider="openai", model="gpt-4o")
        r.append_subagent("sa1", tier="restricted")
        r.publish(EVT_STEP_ACTION, {"tokens": {"input": 1000, "output": 500}})
        r.close_subagent("sa1")
        snap = r.summary_dict()
        assert "subagent_history" in snap
        assert len(snap["subagent_history"]) == 1
        sa = snap["subagent_history"][0]
        assert sa["id"] == "sa1"
        assert sa["tier"] == "restricted"
        assert sa["tokens_in"] == 1000
        assert sa["tokens_out"] == 500
        assert "cost_usd" in sa
        assert sa["cost_usd"] > 0
        assert sa["specialist"] is None

    def test_summary_dict_specialist_field_is_propagated(self):
        r = _run(provider="openai", model="gpt-4o")
        r.append_subagent("sa1", tier="elevated", specialist="deploy-staging")
        r.publish(EVT_STEP_ACTION, {"tokens": {"input": 10, "output": 5}})
        r.close_subagent("sa1")
        snap = r.summary_dict()
        assert snap["subagent_history"][0]["specialist"] == "deploy-staging"

    def test_summary_dict_unknown_provider_yields_zero_cost(self):
        r = _run(provider="unknown-provider", model="unknown-model")
        r.append_subagent("sa1", tier="restricted")
        r.publish(EVT_STEP_ACTION, {"tokens": {"input": 1000, "output": 500}})
        r.close_subagent("sa1")
        snap = r.summary_dict()
        assert snap["subagent_history"][0]["cost_usd"] == 0.0
        assert snap["subagent_history"][0]["tokens_in"] == 1000
        assert snap["subagent_history"][0]["tokens_out"] == 500

    def test_summary_dict_cost_is_zero_when_tokens_zero(self):
        r = _run(provider="openai", model="gpt-4o")
        r.append_subagent("sa1", tier="restricted")
        r.close_subagent("sa1")
        snap = r.summary_dict()
        assert snap["subagent_history"][0]["cost_usd"] == 0.0


class TestSubAgentConcurrency:
    def test_concurrent_publishes_attribute_consistently(self):
        r = _run(provider="openai", model="gpt-4o")
        r.append_subagent("sa1", tier="restricted")
        N = 8
        PER_THREAD = 100

        def publish_thread(delta_in, delta_out):
            for _ in range(PER_THREAD):
                r.publish(EVT_STEP_ACTION, {"tokens": {"input": delta_in, "output": delta_out}})

        threads = [threading.Thread(target=publish_thread, args=(10, 5)) for _ in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected_in = N * PER_THREAD * 10
        expected_out = N * PER_THREAD * 5
        assert r.tokens_in == expected_in
        assert r.tokens_out == expected_out
        sa = r.subagent_history[0]
        assert sa.tokens_in == expected_in
        assert sa.tokens_out == expected_out
        assert r.step_count == N * PER_THREAD


class TestSubAgentSummaryDataclass:
    def test_default_token_fields_are_zero(self):
        s = SubAgentSummary(id="x", tier="restricted", started_at=1.0)
        assert s.tokens_in == 0
        assert s.tokens_out == 0
        assert s.specialist is None
        assert s.ended_at is None

    def test_can_override_token_fields_in_constructor(self):
        s = SubAgentSummary(
            id="x", tier="restricted", started_at=1.0, specialist="deploy-staging", tokens_in=100, tokens_out=50
        )
        assert s.specialist == "deploy-staging"
        assert s.tokens_in == 100
        assert s.tokens_out == 50


class TestSubAgentEventsStillWork:
    def test_subagent_started_event_publishes_normally(self):
        r = _run()
        r.append_subagent("sa1", tier="restricted")
        r.publish(EVT_SUBAGENT_STARTED, {"subagent_id": "sa1", "tier": "restricted"})
        assert not r.events.empty()

    def test_subagent_ended_event_publishes_normally(self):
        r = _run()
        r.append_subagent("sa1", tier="restricted")
        r.close_subagent("sa1")
        r.publish(EVT_SUBAGENT_ENDED, {"subagent_id": "sa1", "tier": "restricted", "status": "ok"})
        assert not r.events.empty()
        assert r.tokens_in == 0
        assert r.tokens_out == 0

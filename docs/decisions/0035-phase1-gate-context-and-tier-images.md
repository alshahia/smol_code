# 0035 - Gate execution-context redesign + real tier images + enforced network posture

**Date:** 2026-08-26
**Status:** active
**Phase:** REMEDIATION-PLAN.md Phase 1 (C1 + C2 + H1)
**Commits:** 357022d (C1), 996c14f (C2+H1)

## Context

The 2026-08-26 full-app review found three critical/high security wiring defects:

- **C1** - the destructive-op gate in `tools/shell.py` / `tools/git.py` fired only when
  `current_session().tier == "full_access"`. The session singleton is PROCESS-GLOBAL;
  under `--orchestrator` (CLI or web) it describes the orchestrator, so every destructive
  op inside delegated elevated/full_access sub-agents - and `git_push` from a plain
  restricted run - executed without confirmation. `cli.py` skipped the full-access prompt
  citing exactly this gate as its backstop, and the orchestrator system prompt told the
  model prompting would happen.
- **C2** - tier images were never reliably real: smolagents 1.26's DockerExecutor defaults
  to `build_new_image=True`, rebuilding the tag from its generic jupyter-kernel Dockerfile
  and silently discarding repo hardening. `full_access.Dockerfile` additionally apt-installed
  CLIs Debian does not ship.
- **H1** - restricted `network="none"` had no runtime enforcement; elevated ip6tables broke
  IPv6 control traffic under default-deny OUTPUT.

## Decision

1. **Gate at the point of execution on tool-bound tier.** Each shell/git tool carries its
   EFFECTIVE tier as a bound class attribute (`tier_name`). The gate fires on
   `is_destructive(tool, kwargs)` regardless of ambient session tier. Tier decides
   allowlists AND deny-vs-prompt: restricted auto-denies; elevated/full_access consult the
   confirm callback unless auto-approved. The classifier also flags `run(git push|reset ...)`.
2. **Child SessionState per delegation (Phase-1 slice of the Phase-5 session refactor).**
   Orchestrator delegations install a child session (correct tier + inherited confirm/diff
   callbacks + audit sink) via `session_scope()`, restoring the parent afterwards. Full
   removal of the process-global pattern remains Phase 5 scope.
3. **Lazy per-run full-access confirmation, fail-closed.** `build_orchestrator_agent(...,
   full_access_gate=...)`: the host plane (CLI y/N + checkpoint + audit; web approval modal)
   supplies a callable invoked once before the first full_access delegation, memoized for
   the run. No gate configured -> PermissionError (refusal), never silent pass-through.
4. **Images are made real or runs are refused.** `smolcode.images.ensure_tier_images()`
   hashes each tier's build inputs into an image label, reuses current images, builds stale
   ones once, raises otherwise. CLI exits 6; web lifespan refuses to boot; executor kwargs
   pin `build_new_image=False`. Dockerfiles repaired (signed vendor repos for kubectl/
   terraform/gcloud/az-cli; pytest+ruff+node where allowlisted; gosu signature-verified).
5. **Restricted egress enforced by topology.** Restricted containers attach ONLY to an
   internal bridge (`smolcode-internal`, idempotently created at boot): no external route.
   Elevated keeps NET_ADMIN + iptables/ip6tables; the v6 chain gains ICMPv6 NDP/PMTUD
   allowances (types 2, 133-136).

## Consequences

+ Destructive ops can no longer bypass confirmation on any plane; the web auto-approve
  endpoint flips a flag the gate actually reads again.
+ Image/allowlist drift is detected by hash and by docker-marked consistency tests
  (every allowlisted command must resolve inside its image).
+ Orchestrator delegations pay one image-hash check per boot and one prompt per run for
  full_access - acceptable friction for the closed hole.
- Auto-approve flips inside a sub-agent apply within that sub-run only (child sessions are
  seeded from the parent; flips do not propagate back until the next delegation seeds anew).
- Base images remain tag-pinned pending digest pinning (how-to documented in the Dockerfiles).
- Full session-model refactor (removing `current_session()` entirely) is still Phase 5.

## Validation

- C1 red->green pinned by `test_gate_context.py` (19F/1P before, 20/20 after).
- C2/H1 units green (`test_images_module.py`, `test_network_posture.py`); docker-marked
  consistency + egress probes require CI Job B (no daemon on the dev host).
- Full non-docker suite green after recovery from three smolcode-checkpoint auto-stashes
  (12:00:27Z, 12:07:50Z, 12:23:05Z); see incident note addendum.

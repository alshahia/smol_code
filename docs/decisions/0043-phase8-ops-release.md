# ADR 0043 — Operations and release plumbing

- **Status:** accepted
- **Date:** 2026-10-24
- **Phase:** 8 of `docs/reviews/2026-09-24-full-app-review/REMEDIATION-PLAN.md`
- **Supersedes:** nothing
- **Depends on:** Phase 3 (decision 0038, wheel/package-data), Phase 1 (decision 0035, tier images), decision 0020 (elevated iptables), decision 0032 (cost caps)

## Context

The 2026-09-24 review's operations row and the 2026-10-24 repair assessment
(ops-medium, A7) found that smolcode could be *run* but not *operated*:

- there was no host-application image, service unit, or run-book; the only
  compose file ships the LiteLLM proxy;
- the FastAPI lifespan's `finally` block was `pass` — shutdown was cosmetic.
  Run threads are daemon threads, MCP subprocesses and the audit file handle
  were never reaped on a normal `SIGTERM`;
- `GET /api/health` returned a static `{"status": "ok"}` and checked nothing —
  not Docker, not the tier images, not the queue, not a failed queue drain, not
  the SPA bundle. A container HEALTHCHECK built on it would always pass;
- tier base images were tag-pinned only (`python:3.12-bookworm`), and the
  source-hash label that decides "rebuild or reuse" covered the Dockerfile
  bytes but not the base image they pulled from. A base-image refresh could
  never invalidate an existing tier image;
- `container_run_kwargs` carried no memory/CPU/PID ceilings;
- nothing warned when a deployment had no cost cap, although every tier can
  spend money;
- `pyproject.toml` had no readme/URLs/classifiers, so the wheel was not
  publishable;
- the Makefile was Windows-only (hard-coded `.venv/Scripts`) while the repo
  advertised `make` targets, and `scripts/install.ps1` hard-coded `py -3.12`;
- `docker/restricted.Dockerfile:10-11` claimed the restricted *import*
  allowlist is enforced by `LocalPythonExecutor` inside the sandbox — it is a
  local-executor feature; under the Docker executor the image is the boundary.

This ADR records what was shipped for those items and, explicitly, what could
not be verified or fixed on this host.

## Decision

### 1. Host-application image and run-book

`smolcode/src/smolcode/docker/Dockerfile.host` builds the **web server** image
(not a tier sandbox): `python:3.12-slim` pinned by digest, the built wheel
installed from `smolcode/dist` (the build context is that directory, so
`.venv`/`node_modules`/`.git` are never sent; the wheel filename is a
required build arg so a stale wheel cannot be baked in), a non-root
`smolcode` user (UID/GID 10001), `EXPOSE 7860`, `ENTRYPOINT ["smolcode",
"web", "--no-browser"]`, `STOPSIGNAL SIGTERM`, a stdlib `HEALTHCHECK` that
GETs `/api/health`, and OCI labels. `docs/operations.md` is the run-book
(build, run, mounts, health, logs, stop/restart, upgrade, threat notes).

**Container networking is deliberately constrained.** The server binds
loopback only (`ALLOWED_BIND_HOSTS` in `web/server.py` and
`_cli_subcommands._web_main`, decision 0010 D1), so `ENTRYPOINT` does *not*
pass `--host 0.0.0.0` — doing so would exit 8 at startup. Inside a container the
process therefore listens on the container's loopback, which `-p` publishing
cannot reach. The run-book documents the two honest options: run the server on
the host (recommended), or use `--network host` on Linux so the container's
loopback *is* the host's. Widening the bind policy would be a security-model
change and is not part of this phase; the run-book says so instead of shipping a
container that cannot be reached.

**Owner decision (2026-10-24): option A — host-run only.** The binding-model
question is settled in favour of running the server on the host: the loopback
bind policy is not widened, no `--network host` requirement is introduced, and
there is no opt-in container port publishing. That keeps decision 0010 D1
intact and avoids mounting the Docker socket into a network-reachable server.

**The run-book's default deployment is the host**: the web server runs on the
host and only tier sandboxes run in Docker. Mounting `/var/run/docker.sock`
into the web-server container gives it the same power as host root (any
container, any mount, `--privileged`), so the document states that explicitly
instead of presenting the socket mount as the normal path.

### 2. Real health snapshot

New `smolcode/src/smolcode/web/health.py`: `build_health_snapshot(settings,
run_manager, uploads_store, *, docker_client=None) -> (payload, status_code)`.
It adds (never removes) fields to the existing body:

| key | meaning |
|---|---|
| `docker` | `"reachable"` / `"unreachable"`; probed through `docker.from_env(timeout=2)` + `ping()` so a dead daemon cannot hang the endpoint |
| `images` | per sandboxed tier: `current` / `stale` / `missing` (label vs `images.source_hash`), or `unknown` when Docker is unreachable |
| `queue_depth` | queued runs |
| `active_run` | run id currently running/awaiting approval/paused, else `None` |
| `queue_drain_error` | last drain failure recorded by the manager (Phase 4) |
| `spa_stale` | bundle older than `web/src` (Phase 7 `web/spa.py`), `None` if the helper is absent |

Status codes: **200 healthy/degraded; 503 only when `SMOLCODE_EXECUTOR=docker`
and the daemon is unreachable.** Under the local executor a dead daemon is
informational, not a failure, so the existing `status == "ok"` contract is
unchanged. The response model for this one route was removed so additive
fields are not stripped by Pydantic; the SPA treats extra keys as optional.

### 3. Graceful shutdown

New `smolcode/src/smolcode/web/shutdown.py`:
`async def graceful_shutdown(app_state, *, timeout: float = 10.0) -> None`.
It accepts `app.state` or the app, tolerates partial state, and never raises.
Sequence: cancel every queued entry **first** (otherwise the active run's
`finally` drain can start the next queued run while shutdown waits for it);
stop every active run through `RunManager.stop()`; join the runner threads
inside one shared `timeout` budget (thread join runs in a worker thread, so the
event loop is not blocked; a run whose thread outlives the budget is logged and
abandoned — daemon threads cannot be killed); close registered MCP servers;
close the audit sink last (it flushes). The lifespan call site stays in `web/server.py` (wired by the Lead, not
this phase) because the app factory owns the lifespan.

### 4. Base-image digest pins + source hash

All three tier Dockerfiles now pin the base by manifest-list digest:

```
ARG PYTHON_BASE=3.12-bookworm@sha256:14a4933e6cef421424f7a66d89a3f4eafcbd0d90e0a822251f298e05132dc735
FROM python:${PYTHON_BASE}
```

`docker/Dockerfile.host` pins `python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704`.
Digests were resolved from the registry API on 2026-10-24 and cross-checked by
hashing the returned manifest body (SHA-256 equals `Docker-Content-Digest`).
Resolution step (reproducible for a future bump):

```
docker manifest inspect python:3.12-bookworm   # take the index digest
# or: GET https://registry-1.docker.io/v2/library/python/manifests/3.12-bookworm
#     Accept: application/vnd.oci.image.index.v1+json
```

`images.source_hash()` now hashes an explicit `base-image-digest` marker
extracted by the new public helper `images.base_image_digest(tier)`
**in addition to** the file bytes, so: the contract is visible where the hash
is defined, a tag-only Dockerfile is rejected with `ImageBuildError`, a
multi-digest Dockerfile is rejected as ambiguous, and a digest bump forces a
rebuild even if someone later stops hashing Dockerfile text. Existing image
hashes change because of the Dockerfile edits — that is expected and is why
`images.ensure` rebuilds once after this lands.

The `elevated` image's gosu step keeps its GPG signature verification and
*adds* a per-architecture SHA-256 pin (values computed locally from the
published v1.17 assets), so a re-uploaded or mirror-substituted asset fails the
build instead of being trusted.

### 5. Container resource limits

`smolagents` 1.26.0 passes `container_run_kwargs` straight to
`client.containers.run(...)`, and Docker SDK 7.2.0 accepts `mem_limit`,
`nano_cpus` and `pids_limit` there, so the limits are expressible without
patching the executor. `Settings.container_limits` (additive) defaults to:

| tier | memory | CPUs | PIDs |
|---|---|---|---|
| restricted | `2g` | 1 | 256 |
| elevated | `4g` | 2 | 512 |
| full_access | (none by default) | (none) | (none) |

`full_access` is the operator's explicit "powerful" tier; imposing a hidden
ceiling would silently break long builds/transfers, so its limits are opt-in
via the same mapping rather than a default. `agents/base.py` converts
`cpus` to `nano_cpus` (the SDK's integer form) and only emits supported keys.

### 6. Startup warning when no cost cap is configured

`config.warn_if_no_cost_caps(settings)` logs one WARNING (per process, never
raises) when `settings.cost_caps == {}`. Both session entry points call it
after settings resolution: `cli.main` (skipped for `--smoke`, whose stub model
cannot spend) and `_cli_subcommands._web_main` (before uvicorn configures
logging, so it lands on logging's last-resort stderr handler). It is advisory
only — no run is refused. Caps stay opt-in (decision 0032); this only removes
the silence.

### 7. Packaging metadata

`pyproject.toml` gains `readme = "README.md"` (the file exists at
`smolcode/README.md`), `[project.urls]` pointing at
`https://github.com/alshahia/smol_code`, and classifiers for Python 3.10–3.13,
OS independence, environment/console/topic groups, plus keywords.
**License and authors (resolved 2026-10-24 by the owner):** MIT, with the
author given as the repository account name `ahmadmhmdsy`. Declared with PEP 639
SPDX metadata (`license = "MIT"` plus `license-files = ["LICENSE"]`, requiring
`setuptools>=77` in `[build-system]`); the license text ships as
`smolcode/LICENSE` (built into the wheel's `dist-info/licenses/`) and a
repository-root `LICENSE` mirror exists for GitHub's license detection. No email
is published.

### 8. OS-aware Makefile and scripts

`smolcode/Makefile` detects `OS=Windows_NT` and selects
`.venv/Scripts` vs `.venv/bin` (resolving `python`, `ruff` and `pytest`
with/without `.exe`), so `make
install|quality|style|test|run|docker-images|clean|help` works on both
platforms. The Windows-only `>nul && echo OK` and POSIX-only `rm -rf` idioms in
`install`/`clean` became portable `python -c` one-liners; a `help` target
documents them. `scripts/install.ps1` no longer hard-codes `py -3.12`: it
tries `py -3`, then `python`, then `python3`, keeps the first reporting
Python >= 3.10, resolves the venv from `$PSScriptRoot` (works from any cwd),
and checks every native exit code. `scripts/quality.ps1` already resolved paths
from `$PSScriptRoot` and is unchanged. `make` is not installed on this host,
so target execution is SKIPPED and `install.ps1` is validated by the PowerShell
parser only (never executed — it would create a venv); see Validation.

### 9. Restricted Dockerfile comment

`docker/restricted.Dockerfile` now says what is true: the import allowlist is
a `LocalPythonExecutor` feature (host/local executor); under the Docker
executor the image contents are the boundary, and the tier's imports list is
advisory there. No behaviour change.

## Consequences

- `GET /api/health` can now return 503, and a container HEALTHCHECK built on
  it becomes meaningful. A web-server container without a Docker socket will
  refuse to boot under the default `docker` executor (fail-closed, unchanged
  from Phase 1) — the run-book documents both the socket warning and the
  host-server deployment.
- New additive API fields; no existing field, key or status-200 path changed.
- The tier image source hash changes for all three tiers once, forcing one
  rebuild. The docker-marked image tests are unchanged in contract.
- Container memory/CPU/PID ceilings apply to new containers only. An operator
  cannot raise them from the CLI yet; that needs a settings/CLI knob, not a
  code constant.
- License and author metadata are now present (MIT + repository account name),
  so the PyPI metadata is complete; publishing itself still needs an explicit
  release action.
- The graceful-shutdown helper is wired into the web lifespan
  (`web/server.py` calls `await graceful_shutdown(app.state)` in the lifespan
  `finally:` block) and covered by the shutdown + web-server tests; the real
  SIGTERM-to-uvicorn path is still only unit-tested.

## Alternatives considered

1. **HAProxy/nginx sidecar + Kubernetes probes** — rejected: the product is a
   single-user loopback tool; the plan explicitly defers orchestration.
2. **A separate health sidecar** — rejected: one endpoint already exists and
   the SPA calls it; adding a process to answer a curl is not a fix.
3. **Digest-pinning through a generated `docker/base.env`** — rejected:
   Dockerfiles must be self-describing when built manually
   (`python -m smolcode.images ensure` is the documented path), and a
   generated file would be a second source of truth shipped in the wheel.
4. **Checksum-only gosu verification (dropping GPG)** — rejected: upstream
   publishes a detached GPG signature per release; the checksum is *added* as
   a second, non-supply-chain-dependent check, not as a replacement.
5. **Imposing full_access container ceilings** — rejected as a default: it
   can break legitimate terraform/rsync workloads in the one tier that exists
   to be powerful. Kept configurable.
6. **Leaving `license`/`authors` unset to unblock PyPI later** — rejected
   once the owner decided (2026-10-24): MIT + repository account name, declared
   as SPDX metadata with a shipped license file.

## Validation

Run on this host (Windows 11, Python 3.13.1 from `smolcode/.venv`) and re-run
after the external auto-checkpoint wipe was recovered (safety commit
`583f495`), so the numbers describe the restored tree.

- `pytest` over the 17 affected modules — the three new ones plus
  `test_packaging`, `test_images_module`, `test_config`, `test_web_api`,
  `test_web_server_phase7`, `test_web_hardening_phase7`,
  `test_network_posture`, `test_composition_boundary_phase6`,
  `test_cost_caps`, `test_local_executor_warning_phase6`,
  `test_agents_base`, `test_run_manager`, `test_tiers`, `test_cli` →
  **247 passed, 0 failed, 0 skipped**.
- New tests alone → **44 passed**: `test_web_health_phase8` 11,
  `test_web_shutdown_phase8` 14, `test_ops_phase8` 19.
- `ruff check` + `ruff format --check` on all 13 changed Python files → clean,
  nothing to reformat.
- `uv build --wheel` into a temporary directory → succeeds; **153 entries**;
  contains `web/health.py`, `web/shutdown.py` and all four
  `docker/*Dockerfile` files; `METADATA` embeds the README (46.4 kB), 4
  `Project-URL`s, 11 classifiers, `Metadata-Version: 2.4`,
  `License-Expression: MIT`, `License-File: LICENSE` and
  `Author: ahmadmhmdsy`; the wheel includes
  `smolcode-0.1.0.dist-info/licenses/LICENSE`. Re-verified on 2026-10-24 after
  the license decision: `test_packaging` → **19 passed**.
- Base-image digests resolved from the registry and cross-checked
  (`Docker-Content-Digest` equals the SHA-256 of the manifest body) for
  `python:3.12-bookworm` and `python:3.12-slim`. gosu 1.17 SHA-256 values were
  computed locally from the published per-architecture assets (the upstream
  `gosu-checksums.txt` asset does not exist — 404).
- `scripts/install.ps1` parsed with the PowerShell language parser → 0 parse
  errors.
- **CI verification (PR #2, run `40112926660`, head `27fd74e`) — all 9 jobs
  pass**: lint ×2, tests ×2, coverage (80% gate), web
  (tsc/oxlint/vitest/Playwright), sandbox-contract (shellcheck + iptables
  contract + firewall e2e on a real daemon), tier-images (**restricted,
  elevated and full_access all build on a real daemon**), packaging (wheel in a
  clean venv + deterministic dead-daemon exit 6), audit (advisory) and
  docs-guard. CI also caught one defect in this ADR's health contract: a
  *local-executor* app reported `degraded` when the runner's daemon had no
  smolcode images even though local runs never touch those images. Fixed in
  `27fd74e`: `status` degrades on image state only when
  `SMOLCODE_EXECUTOR=docker` (the `images` map is still reported), with a
  regression test; `docs/operations.md` §8 states the same rule.

The Dockerfile properties in §1/§4/§8 are additionally asserted by
`test_packaging.py` (digest pin, non-root user, `EXPOSE`, `STOPSIGNAL`,
`HEALTHCHECK` on `/api/health`, `ENTRYPOINT`, source-hash label, package
data), so a regression fails in CI even where no daemon is available.

Not runnable on this host and therefore **NOT verified**:

- `docker build` of `Dockerfile.host` on this host (daemon down) — the tier
  images themselves are now built in CI (see the CI bullet above), but no CI job
  builds the host image, so it stays static-review-only.
- `make` targets (`make` not installed) and `install.ps1` end-to-end (it would
  create a new venv) — parser check only.
- A live `/api/health` 503 against a real unreachable daemon: the unit tests
  use a fake Docker client; the real `docker.from_env` path is exercised only
  for "daemon unreachable at construction".
- A live graceful shutdown against a real uvicorn SIGTERM — the helper is
  wired into the lifespan and unit-tested, but the process signal path is not
  exercised end-to-end here.

## Resolved question (was NEEDS USER DECISION)

**Decided by the owner on 2026-10-24:** `license = "MIT"` and
`authors = [{ name = "ahmadmhmdsy" }]`, declared with PEP 639 metadata and a
shipped `LICENSE` (plus a root mirror). `pyproject.toml` no longer claims
license/author are absent, and `test_packaging` asserts the SPDX expression,
the author, and both files. The remaining non-code blocker for a PyPI release is
no longer metadata — it is the release action itself (and the usual live-Docker
evidence for the sandbox claims).

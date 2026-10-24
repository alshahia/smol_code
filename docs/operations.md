# Operations run-book

**Phase 8 (decision 0043).** How to install, configure, run, upgrade and
troubleshoot smolcode. Architecture and the security model live in
`docs/architecture.md` / `docs/security.md`; this file is the operator view.

## 1. Deployment model (read this first)

smolcode has two runtime planes:

| plane | what runs there | isolation |
|---|---|---|
| **host** | CLI, web server (FastAPI), `RunManager`, MCP servers | loopback-only; same user as the operator |
| **tier containers** | model-written Python (Jupyter kernel per run) | restricted / elevated / full_access images |

**Recommended deployment: the server runs on the host, only the tier sandboxes
run in Docker.** That keeps the process that holds your source tree and provider
keys out of a container with a Docker socket.

A host **application image** (`docker/Dockerfile.host`) exists for packaging and
for Linux hosts, but mounting `/var/run/docker.sock` into it makes that container
equivalent to host root (it can start `--privileged` containers). Read §6 before
using it.

## 2. Prerequisites

- Python **3.10+** (3.12/3.13 tested), `uv` or `pip`.
- Docker Engine / Docker Desktop running (required for the default
  `SMOLCODE_EXECUTOR=docker`). Without a daemon the CLI exits 6 and the web
  server refuses to boot, by design: sandboxed tiers never run on unverified
  images.
- A provider API key for the model you intend to use (see §4).
- POSIX: `make`. Windows: PowerShell 5.1+ (scripts in `scripts/`).

## 3. Install

POSIX (Linux/macOS):

```bash
cd smolcode
make install            # .venv + editable install with dev extras
make quality            # ruff check + format check
make test               # pytest + coverage gate
```

Windows (PowerShell, from any directory):

```powershell
smolcode\scripts\install.ps1     # resolves a Python >= 3.10 (py -3 / python / python3)
smolcode\scripts\quality.ps1     # ruff check + format check (uses .venv next to scripts)
```

The Makefile is OS-aware: `OS=Windows_NT` selects `.venv\Scripts\python.exe`,
everything else uses `.venv/bin/python`. For production installs use
`pip install "smolcode[web]" == <the built wheel>` instead of an editable install.

## 4. Configure (environment)

Resolution order is CLI flag > process env > `.env` (parent `.env` is loaded with
`override=False`) > default. Nothing here is secret-bearing by default; keys come
from the environment only.

| variable | default | meaning |
|---|---|---|
| `SMOLCODE_WORKSPACE` | `<repo>/workspace` | project root bind-mounted into tier containers at `/workspace` |
| `SMOLCODE_EXECUTOR` | `docker` | `docker` (sandboxed) or `local` (**NOT a sandbox**, prints a banner) |
| `SMOLCODE_PROVIDER` | `opencode-go` | `opencode-go`, `MiniMax`, `openai`, `anthropic`, `custom` |
| `SMOLCODE_MODEL` | `deepseek-v4-flash` | provider model id |
| `SMOLCODE_LITELLM_PROXY` | unset | route through a LiteLLM proxy instead of direct providers |
| `SMOLCODE_LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL` |
| `SMOLCODE_UPLOAD_DIR` | `<workspace>/.smolcode/uploads` | upload store |
| `SMOLCODE_UPLOAD_MAX_BYTES` | 50 MB | per-upload cap |
| `SMOLCODE_PROJECTS` | unset | `name1,name2` or `name=path` project registry |
| `SMOLCODE_COST_RATES` | unset | JSON per-model USD rates |
| `SMOLCODE_COST_CAPS` | unset | JSON `{"provider": usd}` daily caps (see §10) |
| `SMOLCODE_ALLOW_UNSANDBOXED_MCP` | `0` | accept that MCP tools run on the host even under the docker executor |
| `SMOLCODE_AUDIT_LOG` | `<cwd>/logs/audit.jsonl` | tamper-evident audit chain |

Provider keys are read from the environment only
(`OPENCODE_GO_APIKEY`, `MINIMAX_API_KEY`, `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `CUSTOM_API_KEY`/`CUSTOM_BASE_URL`, `HF_TOKEN`) — never from
a config file written by smolcode, and never logged (the redaction filter runs on
every log record). Print the resolved configuration with:

```bash
smolcode --print-config
```

## 5. Run

One-shot CLI:

```bash
smolcode --tier restricted "add a unit test for the parser"
smolcode --tier elevated  "open a draft PR for the fix"        # wider allowlist
smolcode --orchestrator   "plan the migration"                  # delegates per tier
```

Web GUI (loopback only — decision 0010 D1):

```bash
smolcode web                # http://127.0.0.1:7860/ and opens a browser
smolcode web --port 7861 --no-browser --log-level debug
```

`--host` accepts only `127.0.0.1`, `localhost`, `::1`; anything else exits **8**.
This is deliberate: the API has no authentication and is not safe on a LAN. For
remote access use SSH port-forwarding or a VPN:

```bash
ssh -N -L 7860:127.0.0.1:7860 user@host
```

Health probe (see §8 for the contract):

```bash
curl -s http://127.0.0.1:7860/api/health | python -m json.tool
```

Stop the server with `Ctrl+C` or `SIGTERM`. The graceful path is
`web.shutdown.graceful_shutdown(app.state, timeout=10.0)`: queued runs are
dropped, the active run gets `stop()` and up to 10 s to finish, MCP servers are
closed, and the audit sink is flushed/closed. A run that ignores the stop flag
past the budget is logged and abandoned rather than blocking shutdown forever
(run threads are daemon threads).

> **Status:** the helper is implemented and unit-tested (Phase 8), but the
> `web/server.py` lifespan still needs to call it — that wiring is owned by the
> Lead's Phase 7 work. Until it lands, `Ctrl+C` stops the process but runs, MCP
> servers and the audit file are not reaped gracefully.

## 6. Docker deployment (optional, advanced)

### 6.1 Build the host image

The image is a pure install of the built wheel; the build context is
`smolcode/dist` so `.venv`, `node_modules` and the git history never reach the
daemon.

```bash
cd smolcode
uv build --wheel
cd ..
docker build \
  -f smolcode/src/smolcode/docker/Dockerfile.host \
  --build-arg SMOLCODE_WHEEL=$(basename "$(ls smolcode/dist/smolcode-*.whl | head -n1)") \
  -t smolcode:host \
  smolcode/dist
```

The wheel filename is a required build arg on purpose: a stale wheel left in
`dist/` must never be silently baked in. The base is pinned by digest
(`python:3.12-slim@sha256:a0f5…`), the build runs as UID/GID 10001, `EXPOSE`
7860, `STOPSIGNAL SIGTERM`, and a stdlib `HEALTHCHECK` polls `/api/health`.

### 6.2 Run it

```bash
docker run -d --name smolcode \
  --network host \
  -e OPENCODE_GO_APIKEY \
  -v /srv/smolcode/workspace:/data/workspace \
  -v /srv/smolcode/uploads:/data/uploads \
  -v /srv/smolcode/audit:/data/audit \
  --group-add "$(stat -c '%g' /var/run/docker.sock)" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  smolcode:host
```

- **The Docker socket is only needed for the default `docker` executor** (the host
  process builds and launches the tier containers). Treat that container as
  host-root: anyone who can reach the API can start a privileged container.
  Prefer running the server on the host (§1).
- **The server binds loopback INSIDE the container** (decision 0010 D1), so port
  publishing (`-p 127.0.0.1:7860:7860`) cannot reach it: the process is not
  listening on the container's external interface. `--network host` (Linux) makes
  the container's loopback the host's loopback and works without weakening the
  bind policy. On Docker Desktop (Windows/macOS) host networking is limited; run
  the server on the host instead. Opening the bind policy is a security-model
  change and is deliberately not shipped here.
- The bind-mounted directories must be writable by UID 10001: either `chown -R
  10001:10001` them or pass `--user "$(id -u):$(id -g)"` and adjust the image
  paths accordingly.
- Without a Docker socket and with `SMOLCODE_EXECUTOR=docker` (the default) the
  container boots, then fails the startup image check (exit 6 / unhealthy).

### 6.3 Logs, stop, upgrade

```bash
docker logs -f smolcode                 # uvicorn + audit lines on stdout
docker inspect --format '{{json .State.Health}}' smolcode
docker stop smolcode                     # SIGTERM -> graceful shutdown
docker rm smolcode
# upgrade:
cd smolcode && uv build --wheel && cd ..
docker build ... -t smolcode:host smolcode/dist   # same command as 6.1
docker stop smolcode && docker rm smolcode && docker run ... (as 6.2)
```

Upgrade order matters: build the new image, then restart; the workspace,
uploads and audit chain are on volumes and survive `docker rm`.

## 7. Tier sandbox images

Tier images are built on demand from `smolcode/docker/*.Dockerfile`:

```bash
python -m smolcode.images ensure                    # all three, boot-time code path
python -m smolcode.images ensure --tier restricted
python -m smolcode.images hash restricted           # current source hash
make docker-images                                  # same as ensure
```

Each image carries an `org.opencontainers.image.smolcode.source-hash` label. The
hash covers the Dockerfile, every file it COPYs (e.g. `iptables-init.sh`) **and
the digest-pinned base image**; `ensure` rebuilds only when the label differs.
Every tier Dockerfile pins its base by digest, so a repointed tag cannot silently
change a sandbox. A missing/stale image that cannot be built exits **6** — the
process never falls back to an unverified executor image.

Refresh the base pin (rare; do it deliberately):

1. Resolve the new digest:
   `docker manifest inspect python:3.12-bookworm` (or the registry API with an OCI
   index `Accept` header).
2. Replace the `sha256:…` in the `ARG PYTHON_BASE` default of all three tier
   Dockerfiles (and `Dockerfile.host`'s `FROM` for the slim image).
3. Rebuild (§7) — the hash changes, so `ensure` rebuilds exactly once.

`elevated` fetches `gosu` 1.17 at build time and verifies it twice: the upstream
GPG signature and a per-architecture SHA-256 pinned in the Dockerfile. The
`full_access` image's HashiCorp apt step is **BLOCKED upstream** (HTTP 404 for
`apt.releases.hashicorp.com` since 2026-09-24); the build fails honestly rather
than trusting an unverified key, so `terraform` cannot be provisioned from that
repo until upstream returns. The comment block in `full_access.Dockerfile` has the
re-check command.

## 8. Health endpoint contract

`GET /api/health` returns a JSON snapshot and one of two status codes.

| field | values | meaning |
|---|---|---|
| `status` | `ok` / `degraded` / `unhealthy` | roll-up |
| `version` | string | smolcode version |
| `uploads_dir`, `uploads_count` | string / int | upload store (pre-existing fields) |
| `docker` | `reachable` / `unreachable` | daemon probe (`docker.from_env(timeout=2)` + `ping()`) |
| `images` | `{tier: current|stale|missing|unknown}` | label vs `images.source_hash` |
| `queue_depth` | int | queued runs |
| `active_run` | run id or `null` | running / awaiting-approval / paused |
| `queue_drain_error` | string or `null` | last queue-drain failure |
| `spa_stale` | `true` / `false` / `null` | SPA bundle older than `web/src` (`null` = helper unavailable) |

Status codes:

- **200** — healthy, or `degraded` (reachable daemon but an image is stale/missing;
  serving still works and boot already guards the first run).
- **503** — only when `SMOLCODE_EXECUTOR=docker` **and** the daemon is unreachable.
  Under `local` a dead daemon is informational and the historical 200/`ok`
  contract holds.

Use it for liveness/readiness probes but note 503 means "cannot execute at all",
not "the process is dead": restarting will not fix a stopped Docker daemon.

## 9. Resource limits on sandbox containers

Defaults (decision 0043, `Settings.container_limits`):

| tier | memory | CPUs | PIDs |
|---|---|---|---|
| restricted | 2g | 1 | 256 |
| elevated | 4g | 2 | 512 |
| full_access | — | — | — (opt-in) |

`full_access` has no hidden ceiling: it exists to run heavy tools, and a silent
RAM cap there looks like a random OOM. Limits are `docker run` kwargs
(`mem_limit`, `nano_cpus`, `pids_limit`) forwarded by the DockerExecutor; they
apply to new containers only and are visible in `smolcode --print-config`.
Override programmatically (there is no CLI knob yet):

```python
from smolcode.config import Settings, load_settings
settings = load_settings().with_overrides(container_limits={
    "restricted": {"mem_limit": "1g", "cpus": 0.5, "pids_limit": 128},
    "elevated": {"mem_limit": "8g", "cpus": 4, "pids_limit": 1024},
    "full_access": {"mem_limit": "16g"},
})
```

An explicit mapping replaces the whole defaults mapping (per tier). Invalid
values raise `ValueError` at agent-build time instead of running unbounded.

## 10. Cost caps

Spend caps are opt-in (decision 0032). Set them in the environment or at runtime:

```bash
export SMOLCODE_COST_CAPS='{"MiniMax": 1.00, "openai": 5.00}'   # USD per provider per day
```

or `PUT /api/cost-caps` from the GUI. When no cap is configured, startup logs
**one** WARNING (`smolcode.config`: "no per-provider cost cap configured …") and
continues. It is advisory, once per process, and absent when any cap is set;
`--smoke` runs never emit it (the stub model cannot spend).

## 11. Cross-platform command matrix

| task | POSIX | Windows |
|---|---|---|
| install | `make install` | `scripts\install.ps1` |
| lint/format check | `make quality` | `scripts\quality.ps1` or `scripts\quality.cmd` |
| auto-fix | `make style` | `ruff check src --fix; ruff format src` |
| tests | `make test` | `.venv\Scripts\pytest src/smolcode/tests` |
| CLI | `make run ARGS='--tier restricted "…"'` | `.venv\Scripts\smolcode --tier restricted "…"` |
| tier images | `make docker-images` | `.venv\Scripts\python -m smolcode.images ensure` |
| clean | `make clean` | `make clean` (portable Python one-liner) |

## 12. Troubleshooting

| symptom | cause / fix |
|---|---|
| exit **2** | configuration error (`ConfigError`): unknown provider/executor/log level, bad cap JSON, unwritable workspace. Read the message; `--print-config` shows the resolved values. |
| exit **3** | missing provider API key (`MissingAPIKey`). Export the env var named in the message. |
| exit **6** | tier image missing/stale and cannot be built: daemon down, registry unreachable, or the known HashiCorp 404 (§7). Fix the build, then retry; never bypass. |
| exit **7** | web extras not installed: `pip install "smolcode[web]"`. |
| exit **8** | refused bind host: use `127.0.0.1`/`localhost`/`::1` and tunnel instead (§5). |
| exit **130** | interrupted (Ctrl+C / SIGTERM to the run): expected; the run was stopped, check the audit log for the last completed step. |
| `/api/health` → **503** | executor is `docker` and the daemon is unreachable. Start Docker / fix `DOCKER_HOST`. |
| `/api/health` → `status: degraded` | daemon reachable but a tier image is `stale`/`missing`: run `python -m smolcode.images ensure`. |
| `spa_stale: true` | `web/dist` is older than `web/src`: rebuild the SPA (`cd web && npm ci && npm run build`). |
| `queue_drain_error` set | the last queued run failed to start (settings/model/executor): fix the cause, then enqueue again. |
| container restarts during a long run | the 10 s shutdown budget was exceeded: the run was stopped mid-way (check the audit log). Raise patience only by giving runs less work per step. |
| MCP tools do not work under docker | intended: MCP tools run on the host, so they are refused unless `--allow-unsandboxed-mcp` (R13). |

## 13. Security notes

- Never publish port 7860 beyond loopback. The API has no auth and can start
  agent runs (and, with MCP or the docker executor, reach the shell).
- Never commit `.env`/`logs/`; the audit log is redacted on write but still local.
- The audit chain (`logs/audit.jsonl`) is append-only and rotated with
  `python scripts/rotate_audit_log.py`; keep the old files.
- `SMOLCODE_EXECUTOR=local` is **not a sandbox** and prints a banner; use it only
  for trusted debugging.
- The Docker socket is host-root. If you cannot accept that, run the server on
  the host (§1).

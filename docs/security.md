# Security Model

**Date:** 2026-06-28
**Author:** initial planning pass
**Status:** active
**Related:** `docs/environment.md`, `docs/architecture.md`, `docs/roadmap.md`

---

## 1. Threat model in one paragraph

The agent receives a task from a (potentially adversarial) human user or
from an upstream orchestration system. The task is sent to a hosted LLM
(LiteLLM-routed). The LLM returns natural-language reasoning **and** a
Python code snippet (or tool call) intended to advance the task. The
system runs that snippet on the user's host. The threat is that the
snippet — whether by prompt injection, jailbreak, or genuine but
over-permissioned intent — escapes the intended scope: reads files it
shouldn't, modifies state it shouldn't, calls the network, exfiltrates
secrets, or pivots to other systems.

**Everything in this document is about narrowing the blast radius of
that one snippet.**

---

## 2. Hard constraints (carried from the user brief)

These are **non-negotiable**, regardless of tier:

1. Model-written Python **never** executes on the host without a
   sandbox. Default executor is Docker (`smolagents[docker]`); `local`
   is an **opt-in** fallback for environments where Docker is unavailable
   and is explicitly labelled "not a sandbox" in the CLI. On the current
   host (Docker daemon running), `SMOLCODE_EXECUTOR=docker` is the
   default and the `local` fallback is unused.
2. **No agent gets unrestricted filesystem, network, or system access.**
   Even `full_access` is bounded by the tier's allowlist.
3. **No secrets in source or committed config.** All API keys come from
   env vars (or a gitignored `.env` with `chmod 600`). The CLI
   refuses to start if a configured provider's key is missing.
4. **No bypass knobs that weaken the security model.** There is no
   `--dangerously-skip-permissions` flag. There is no `--allow-any-import`.
   There is no `--bypass-workspace`.
5. **No assumption of unverified tools or services.** MCP servers,
   providers, and shell commands are all enumerated in config and
   validated at startup.

---

## 3. The three tiers, in detail

### 3.1 Restricted (the default)

**Trust assumption:** the model is helpful but may be tricked into
running dangerous code via prompt injection. The agent should be able
to do everyday coding tasks — read, lint, test, format, search — but
nothing that touches the network or mutates state outside the
workspace.

| Capability | Allowed? | Notes |
|---|---|---|
| Read files in `workspace/` | yes | `PathPolicy.resolve_under_workspace` |
| Write files in `workspace/` | yes | Same gate |
| List directories in `workspace/` | yes | Same gate |
| Python imports | `json`, `pathlib`, `ast`, `textwrap`, `re`, `math`, `itertools`, `collections`, `datetime`, `typing`, `dataclasses`, `statistics`, `hashlib` (read-only digests) | Anything else → `additional_authorized_imports` rejects. |
| Shell commands | `python`, `pytest`, `ruff`, `git` (read-only subcommands only), `cat`, `head`, `tail`, `wc`, `find` (within workspace), `grep` | `shell.run` basename allowlist; `subprocess.run(shell=False)` always. |
| Network | **none** | Container `network_mode="none"`. No outbound socket of any kind. |
| MCP servers | readonly (`^(get|search|read|list)_` prefix) | `mcp_tools` wrapper rejects non-readonly. |
| `max_steps` | 20 | Bounds compute + LLM cost. |
| Wall-clock timeout | 60 s | `agent.run()` is wrapped in `asyncio.wait_for`. |

### 3.2 Elevated (opt-in, used for tasks like "open a PR")

**Trust assumption:** the user has authorised the agent to perform
network-bounded actions (push to a remote, open a ticket) that the
restricted tier cannot. Elevated is **not** an "anything goes" tier; it
is "network + the tools needed for code review and deployment prep".

| Capability | Allowed? | Notes |
|---|---|---|
| Filesystem | workspace + extras in `TIERS.elevated.paths` (config-driven allowlist) | Each extra path is a single resolved absolute path; symlinks rejected (`SEC-10` pattern from sibling project). |
| Python imports | restricted ∪ `subprocess` (used only inside `shell.run`), `tomllib`, `csv`, `io`, `urllib.parse`, `http.client` (for the allow-listed hosts only) | `socket` is **not** in this list. |
| Shell commands | restricted ∪ `npm`, `pnpm`, `cargo`, `make`, `git` (full subcommands, no `-i`), `curl` (allow-listed hosts via wrapper), `docker client` (read-only commands: `ps`, `images`, `logs`) | All still go through the basename allowlist. |
| Network | restricted to a host allowlist in `TIERS.elevated.network_allowlist` | Enforced by container `network_mode="bridge"` + iptables (Milestone 4). v1 ships the allowlist data structure; the enforcement lands in M4. |
| MCP servers | readwrite (ticketing, CI trigger) | The wrapper verifies the tool name does not match a `full_access`-only pattern. |
| `max_steps` | 40 | |
| Wall-clock timeout | 300 s | |

### 3.3 Full-access (explicit, audited)

**Trust assumption:** the user has set up a specialist agent for a
narrow, well-understood workflow (deploy to staging, run a data
pipeline, push a release branch). The agent runs **only** if invoked
explicitly (`--tier full_access`) and **only** after a per-run
confirmation prompt (`Confirm full-access run? [y/N]`). Every
full-access run writes an `AuditEntry` to `logs/audit.jsonl`.

| Capability | Allowed? | Notes |
|---|---|---|
| Filesystem | workspace + per-agent `extra_paths` | Each specialist agent declares its own extra paths; nothing is implicit. |
| Python imports | elevated ∪ `socket`, `asyncio`, `requests`, `httpx`, `paramiko` | Still no `ctypes` and no `importlib` magic. |
| Shell commands | elevated � `ssh`, `rsync`, `kubectl`, `terraform`, `helm` (where installed) | |
| Network | broader, per-config | Still no raw socket creation outside the agent process. |
| MCP servers | full set | Including any future write-capable servers. |
| `max_steps` | 80 | |
| Wall-clock timeout | 900 s | |

---


### 3.4 User uploads (M8, decision 0010 D8)

User-uploaded files live in a hidden dot-folder under the workspace:
`<workspace>/.smolcode/uploads/`. Every upload is
sanitised, MIME-sniffed (the browser-claimed MIME is IGNORED), size-capped,
SHA-256-hashed, and recorded in an append-only `.uploads.jsonl`
sidecar. The default size cap is 50 MB; the default MIME allowlist is
text + docs (PDF, DOCX, XLSX) + images (PNG, JPG, GIF, WebP) + code.

The default behaviour of the three tiers for uploads:

| Tier | Read uploads | Modify uploads | Delete uploads |
|---|---|---|---|
| `restricted` | yes (via `read_file`) | **no** (`write_file` raises `PermissionError` on uploads path) | no (only the user via the GUI / CLI) |
| `elevated` | yes | yes | yes |
| `full_access` | yes | yes | yes |

The `restricted`-tier write-block is enforced **inside**
`_WriteFileTool.forward()`, not at the API layer, so it
applies to every code path (CLI, web SPA, future programmatic
callers). The check uses `os.path.commonpath` after
`os.path.realpath` to defeat symlink and case-folding tricks.

Uploads are **persistent by default**. There is no TTL — the user
explicitly required "do not lose my files" (decision 0010 D8 Q4).
Deletion is always explicit: per-file button in the GUI,
`smolcode uploads delete`, or `smolcode uploads clean --yes`
for bulk. Every upload and delete emits an `upload.add` /
`upload.delete` event in the audit log so the trail is complete.

The full upload design is in `docs/decisions/0010-gui-design.md` D8.

---
## 4. Layered controls

Even within a tier, multiple independent layers must be bypassed for a
genuine escape. The layers (innermost first):

```
+----------------------------------------+
| 1. Container OS (Linux, non-root)      |
| 2. Capability drops (cap_drop=ALL...)  |
| 3. network_mode (none / bridge / host) |
| 4. Read-only root filesystem (Tier 1)  |
| 5. tmpfs-only writable dirs (Tier 1)   |
| 6. PIDs limit / memory cgroup         |
| 7. additional_authorized_imports       |
|    (smolagents LocalPythonExecutor)    |
| 8. host-side PathPolicy                |
|    (workspace boundary on fs/shell)    |
| 9. host-side command allowlist         |
|    (basename match in shell.run)       |
| 10. Tier policy in config.py           |
|     (Settings + Tier dataclasses)      |
| 11. Wall-clock timeout (asyncio.wait)  |
| 12. max_steps (CodeAgent built-in)     |
| 13. Audit logging (full_access only)   |
+----------------------------------------+
```

If layer 7 is bypassed (the agent somehow gets a non-allow-listed import
in), layer 1-6 still constrain what the code can do. If layers 8-9 are
bypassed (a tool is invoked with `..` paths), layer 7 still rejects
the dangerous imports. If layers 1-6 are bypassed (e.g., `local`
executor fallback), layers 7-13 still apply. **No single bypass breaks
the model.**

---

## 5. Path policy

The `PathPolicy` helper is the host-side gate for every filesystem
and shell operation. It enforces:

1. **Workspace containment.** Every path is resolved with
   `Path.resolve()` (which follows symlinks) and then checked with
   `is_relative_to(workspace)`. Symlinks that escape the workspace
   are caught at resolve time, not at use time.
2. **No traversal.** Paths containing `..` after the workspace
   check are re-resolved and re-checked (defence against partial
   resolve races). `os.path.realpath` + `os.path.normcase` on
   Windows handles case-insensitive filesystems and junctions
   (`SEC-10` pattern from sibling project).
3. **Explicit per-tier paths.** Elevated and full_access can declare
   `extra_paths` in config; the policy accepts only those exact
   paths. There is no `extra_paths_glob`.
4. **SHA-256 attestation.** Every file written by the agent is hashed
   before write and recorded in the run log; the agent cannot
   silently mutate a file it did not declare it was touching.
5. **Read-only mounts.** For Tier 1 we will mount known read-only
   data (system docs, vendored packages) into the container as
   `:ro`; the agent cannot modify them even if it bypasses layers
   7-9.

---

## 6. Command policy

The `shell.run` tool's contract:

- **No `shell=True`.** Always `subprocess.run([cmd, *args], shell=False)`.
- **Basename allowlist.** `cmd` is tokenised; the first token's
  basename must appear in `tier.commands`. There is no regex; there
  is no `startswith`.
- **No untrusted argv.** Args are passed positionally; the agent
  cannot inject shell metacharacters because there is no shell to
  interpret them. `; `, `&&`, `|`, redirections all fail with a
  clear error rather than executing.
- **Timeout.** Every `subprocess.run` has a `timeout` kwarg set
  from the tier's `timeout_s` (or shorter, per-command).
- **Capture output.** `stdout` and `stderr` are captured, not
  streamed, so the agent cannot spam the user's terminal.
- **No backgrounding.** `&` and `nohup` are rejected by the
  basename allowlist (neither is a registered command).



---

## 7. Network policy

### 7.1 Restricted tier

Container `network_mode="none"`. No socket syscall can succeed
because there is no network namespace with a default route. The
agent cannot call out to fetch a payload, cannot phone home, cannot
make DNS queries.

### 7.2 Elevated tier

Container `network_mode="bridge"` + iptables allow-list (Milestone 4
work — v1 ships the data structure `TIERS.elevated.network_allowlist`
and refuses to run elevated with an empty list). The allow-list is
host-glob patterns (`*.github.com`, `pypi.org`, etc.); anything
outside the list is REJECT (DROP, not silently passed). DNS is also
allow-listed.

**Forward-looking (planned for M16, decision 0017):** the current
`network_allowlist` is documented and passed to the container as the
`SMOLCODE_NETWORK_ALLOWLIST` env var, but M4–M13 do NOT install the
iptables rules inside the container. M16 will close this gap by
shipping a new `docker/elevated-iptables.Dockerfile` that runs an init
script as PID 1 with `CAP_NET_ADMIN`, reads the allowlist from
`SMOLCODE_NETWORK_ALLOWLIST`, applies OUTPUT chain rules (ACCEPT for
allow-listed CIDRs/hosts, DROP for everything else), and emits an
`iptables_install` audit event before the agent process starts. The
container is otherwise unchanged. Risk note: `CAP_NET_ADMIN` is broad;
M16 will install the init script as PID 1 and run all subsequent
processes as non-root inside the container. See decision 0017 for the
full design and risk register.

### 7.3 Full-access tier

`network_mode="bridge"` with no host allow-list (or a per-agent
allow-list). Still no `network_mode="host"` — that would bypass
container isolation entirely.

### 7.4 Outbound MCP servers

MCP servers reachable over `streamable-http` are subject to the
same network policy as any other outbound call. An MCP server that
the tier's network policy rejects cannot be reached, even if its URL
is configured.

---

## 8. Secrets policy

| Concern | Mitigation |
|---|---|
| API key in source | None. We refuse to merge any commit containing a key matching `sk-`, `sk-ant-`, `hf_`, `ghp_`, `gho_`, `ghu_`, `ghs_`, `AIza*`, `AKIA*`, etc. (M7 + M13 prefixes, see `smolcode/redact.py:DEFAULT_PATTERNS`; `SEC-18` pattern from sibling project). |
| API key in `.env` | `chmod 600`, gitignored, never logged. |
| API key in CLI args | `--api-key` is **not** a flag. Keys come from env only. |
| API key in process env of the agent container | The container env is a **whitelist** (`KG_AUTH_TOKEN`, `PATH`, no `MINIMAX_API_KEY`, no `OPENCODE_API_KEY`). The agent's LLM calls go through the host, not the container. |
| Key leak via structured logs | A single `RedactSecretsFilter` redacts any value matching `*KEY=*...`, `sk-...`, `hf_...`, `ghp_...`, `gho_...`, `AIza...`, `AKIA...`, etc., before log emission (`SEC-4` pattern from sibling project; 9 prefixes as of M13). |
| Key in crash dump | The CLI catches exceptions and emits a structured error; raw tracebacks are not printed when a key is in `os.environ`. |
| Web UI traceback leak (decision 0024) | `agent_runner.run_in_thread`'s broad `except Exception` block now appends `traceback.format_exc()` to `run.error` AND surfaces it in the `EVT_ERROR.traceback` SSE field. The `RedactSecretsFilter` is applied to all SSE events before publish (per `web/api.py` + `redact.py`), so any API key, OAuth token, or env-var value that lands in a traceback frame variable name is scrubbed before it leaves the server. Capped at 8 KB so a runaway traceback cannot blow up the SSE queue. |
| Provider response caching | LiteLLM's `caching` plugin is **off** by default. Enabling it stores API responses on disk and could leak data across runs. |
| Token usage surfaced in CLI | `TokenUsage` is shown but the response text is **not** written to disk by default; the user must `--save-run <path>` to opt in. |

**Third-party integration surface (M15.2, decision 0019):** External
integrators that need to redact known secret prefixes (e.g. a custom
log shipper, a webhook transformer) should call the public helper
`smolcode.redact.redact_string(s, patterns=None, min_token_len=10)`.
When `patterns=None` the helper applies the same `DEFAULT_PATTERNS`
that the in-process `RedactSecretsFilter` uses, so log output stays
consistent regardless of whether the originating record went through
the logging factory or was redacted by an external pipeline. Pass an
explicit `patterns` iterable to REPLACE the defaults (combine with
`list(DEFAULT_PATTERNS) + extra` to augment). The prior private
`_redact_string` is gone — clean in-repo break in M15.2, no
deprecation alias.

---

## 9. Audit log

`full_access` runs are written to `logs/audit.jsonl` (one JSON
object per line). As of **M13** every line also carries a SHA-256
hash chain (`prev_hash` + `entry_hash`) so silent tampering with
prior entries can be detected by replay. Use `smolcode audit verify`
to confirm chain integrity (CI-friendly; exit 0 = clean, exit 1 =
tampered/unverifiable). See `docs/decisions/0016-m13-audit-integrity-redact-expansion.md`
for the chain construction and `smolcode/src/smolcode/audit.py:verify_chain`
for the verifier. The chain is **on by default**; set
`SMOLCODE_AUDIT_HASH_CHAIN=1` to disable (not recommended).

Each entry contains:

```jsonc
{
  "ts": "2026-06-28T14:33:01Z",
  "tier": "full_access",
  "agent": "deploy-staging",
  "task": "deploy commit abc123 to staging",
  "user": "ahmad",
  "host": "workstation-1",
  "pid": 12345,
  "model": {"provider": "MiniMax", "model_id": "MiniMax-M3"},
  "tools_called": ["shell.run", "git.push", "kubectl.apply"],
  "files_written": ["/workspace/src/x.py", "/workspace/.git/refs/heads/main"],
  "duration_s": 47.2,
  "token_usage": {"input": 8123, "output": 1456},
  "exit_status": "success",
  "errors": []
}
```

The audit log is **append-only** (write mode `'a'`, never `'w'`)
and rotates via `smolcode audit rotate --keep-days N` (M14.3,
decision 0018). The CLI verb pre-verifies the chain and **refuses
to rotate a tampered log** (exit code 4), so a broken chain is
never silently gzipped and held forever. The standalone
`scripts/rotate_audit_log.py` predates this guarantee; prefer the
CLI verb for any new deployment.

`restricted` and `elevated` runs are **not** written to the audit
log by default (the volume would be enormous); a separate `INFO`
log captures everything at the user's option via
`SMOLCODE_LOG_LEVEL=DEBUG`.

Operators read the log four ways (all apply `RedactSecretsFilter`
so leaked keys cannot escape):

- `smolcode audit ls [-n N]` — quick terminal scan
- `smolcode audit grep <pattern>` — case-insensitive substring
- `smolcode audit grep --patterns <re1> <re2> ...` — regex (M14.4)
- `GET /api/audit?limit=&grep=&verify=1` — SPA viewer
  (`smolcode/web/src/components/AuditPanel.tsx`, decision 0018 M14.2)

Full retention policy (size, age, archive sweep, backup) lives in
[`docs/audit-log-retention.md`](./audit-log-retention.md).

---

## 10. Threat-by-control matrix

| Threat | Container | PathPolicy | CmdPolicy | NetPolicy | ImportPolicy | Timeout | max_steps | Audit |
|---|---|---|---|---|---|---|---|---|
| Read file outside workspace | Y | Y | n/a | n/a | n/a | n/a | n/a | n/a |
| Write file outside workspace | Y | Y | n/a | n/a | n/a | n/a | n/a | logged |
| Run arbitrary binary | Y (cap_drop) | n/a | Y | n/a | n/a | Y | Y | logged |
| Install pip package | Y | n/a | Y (allowlist) | Y (pypi.org only for elevated) | n/a | Y | Y | logged |
| Open outbound socket | Y (network_mode) | n/a | n/a | Y | n/a | n/a | n/a | logged |
| Import `os`, `subprocess` | n/a | n/a | n/a | n/a | Y | n/a | n/a | n/a |
| Import `ctypes`, `importlib` | n/a | n/a | n/a | n/a | Y | n/a | n/a | n/a |
| Loop forever | Y (PIDs limit) | n/a | n/a | n/a | n/a | Y | Y | logged |
| Exfiltrate via DNS | Y (network_mode) | n/a | n/a | Y | n/a | Y | n/a | logged |
| Prompt injection → privilege escalation | n/a (tier is set at boot) | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

The last row is the **only** threat this system does not engineer
against: a successful prompt injection that convinces the user to
run `--tier full_access` is on the user, not on the system. The
per-run confirmation prompt (`Confirm full-access run? [y/N]`) is
the only friction we add — and it is intentionally easy to confirm
because the user has opted in to the tier by passing the flag.

---

## 11. What we explicitly do **not** defend against

In the spirit of honest threat modelling, here is what is out of
scope:

- **The user themselves.** If the user types `y` at the confirmation
  prompt, the agent runs. We do not second-guess the user.
- **Compromise of the host kernel or Docker daemon.** A compromised
  daemon can do anything; no userland controls help.
- **Side channels.** Spectre / Rowhammer / cache-timing. Out of scope.
- **LLM hallucination that produces wrong-but-not-malicious code.**
  That is an accuracy problem, not a security problem; the system
  is indifferent to whether the agent's code is correct as long as
  it is contained.
- **Physical access to the host.** If an attacker has physical
  access, all bets are off.
- **Compromise of a provider.** If the LLM provider's API is
  compromised, the attacker controls the model's outputs and we
  cannot help.

---

## 12. Security testing plan

Per the project's testing discipline (`smolagents/AGENTS.md` →
`make quality` then `make test`), every milestone ends with:

1. **Static:** `ruff check` + `ruff format --check`.
2. **Unit:** `pytest` with `--cov-fail-under=80`.
3. **Security tests** (in `tests/test_security.py`):
   - Tier policy cannot be downgraded by env var (`SEC-2`).
   - `shell.run` rejects `..`, `;`, `&&`, `|`, `>`, `<`.
   - `PathPolicy.resolve_under_workspace` rejects symlinks that
     escape the workspace.
   - `MCPClient` readonly mode rejects `delete_*` tool names.
   - `RedactSecretsFilter` redacts `sk-`, `sk-ant-`, `hf_`,
     `ghp_` in log output.
   - `AuditSink` rejects `'w'` mode.
4. **Smoke:** `--smoke` exercises every tier with the stub model
   and asserts each allowlist is honoured.

Milestone 5 ships the full security test suite; Milestone 1 ships the
basics (`shell.run` + `PathPolicy` rejection tests).

### 3.5 Web Live Execution (M9)

**Status:** SHIPPED 2026-08-21 (decision 0012).

The web GUI exposes the agent loop via `POST /api/runs` +
`GET /api/runs/{id}/events` (SSE). The threat model change vs M8
(read-only viewer) is: **the web now triggers code execution**. The
following controls apply.

**Threat model (M9)**

- The server binds to loopback only (`ALLOWED_BIND_HOSTS`); the SPA
  is reachable only via `http://127.0.0.1:7860`. A malicious web
  page CANNOT reach the API (different origin + localhost bind).
- The host-side tools (fs/shell/git) still run inside the per-tier
  Docker executor (or `local` with `--smoke`). M9 does not weaken
  this isolation; it only exposes the loop to a different driver.
- The `session.confirm_callback` (M4.x) is bridged to a POST-able
  approval gate. The SPA shows a modal; the user clicks Approve
  / Deny / Approve-for-rest-of-run; the click POSTs to
  `/api/runs/{id}/approval`. Timeout (default 30 s) = deny.

**Controls**

- **`full_access` is rejected from the web with HTTP 403.** Decision
  0012. The full_access tier requires a real interactive `y/N`
  prompt on stdin (per decision 0006). The SPA has no stdin. To
  grant full_access the user must use the CLI. The SPA's tier
  switcher omits full_access entirely.
- **`Stop` is cooperative, not preemptive.** The stop flag is
  checked between agent steps. A run that has already issued a
  destructive shell command cannot be un-done; it can only be
  halted at the next step boundary. The audit log records the
  destructive call + the stop request, so recovery is possible via
  `git stash pop` (M4.x checkpoint) or filesystem rollback.
- **The approval modal shows the full args before approval.**
  Per 0010 D5 (security-first UX). The user sees the exact
  command the agent wants to run; they can deny with one click.
  v1.1 may add an "Edit args" path (per the design sketch in
  0010); out of scope for M9.
- **The audit log records every approval decision** (`destructive_decision`
  event with `run_id`, `tool`, `summary`, `approved`, `reason`).
- **The SPA never holds an API key.** All LLM calls go through the
  FastAPI process; the key stays in the server's env. The SPA only
  sees the request/response payloads.
- **SSE frames do NOT include secrets.** The agent loop redacts
  via `RedactSecretsFilter` (M7) before any event payload is
  serialised. Step observations may contain tool outputs; if those
  outputs include a secret the redaction marker replaces it.

**Out of scope (v1.1+)**

- CSRF token on mutating endpoints.
- Bearer-token auth + login page.
- Replay buffer so SSE subscribers see events that arrived before
  they connected.
- Mid-run tier switch (the SPA's switcher only affects the NEXT run).

### 3.6 Inline Diff Gate + Workspace Tree (M10)

**Status:** SHIPPED 2026-08-23 (decision 0013).

M10 is the next slice of v1.3: every `write_file` and `patch_file`
call goes through a **diff gate** that publishes the proposed
before/after to the SPA via `diff.proposed` and blocks until the
user Approves, Edits + Approves, or Denies. The SPA also renders
a workspace tree that highlights files the run has touched. M10
introduces NO new execution surface — the fs tools were already
present, the gate was already plumbed in M9 (0012 §F4). M10 only
adds the UX layer.

**Threat model (M10)**

- **The diff gate is the new write-control point.** Every write to
  the workspace (whether full-file `write_file` or patch `patch_file`)
  MUST pass through `SessionState.diff_callback` when the gate is
  on (default `SMOLCODE_WEB_DIFF_GATE=1`). The callback publishes
  the full diff payload to the SPA; the SPA's modal blocks until
  the user responds or the timeout fires (default 30 s, deny on
  timeout).
- **The user can edit the proposed content.** `edited_after` is a
  free-form string the user types in the SPA's DiffViewer. It is
  sent back to the runner via `POST /api/runs/{id}/approval` and
  applied in place of the agent's proposal. The audit log records
  `edited=true` so a reviewer can distinguish "agent proposed
  this" from "user rewrote it".
- **The user can flip auto-approve for the rest of the run.**
  `auto_approve_now=True` from the callback sets
  `SessionState.auto_approve_diff = True`; subsequent write_file /
  patch_file calls in the same run bypass the gate. This matches
  the M9 destructive confirmation auto-approve flow.
- **Auto-approve does NOT persist across runs.** Each run starts
  with `auto_approve_diff = False`. A new run requires fresh
  approval for every write.
- **The workspace tree is read-only.** `GET /api/workspace/tree`
  walks the workspace via `diffs.walk_tree` (limited to 5000
  entries, 10 levels deep by default; both clamped 1..20000 /
  1..20). The endpoint does not modify anything. Hidden dotfile
  directories are skipped EXCEPT `.smolcode` so the uploads
  folder remains visible; common noise dirs (`.git`,
  `__pycache__`, `node_modules`, `.venv`, `venv`, `.tox`) are
  always skipped.
- **No new outbound traffic.** The diff gate is local-only (the
  SPA + FastAPI on the same loopback). No external service sees
  the diff payload.

**Controls**

- **Atomic write via `tempfile.mkstemp` + `os.replace`.** Every
  successful `patch_file` write goes through a temp file in the
  same directory and an atomic rename. A partial write does NOT
  leave a truncated file on disk. If the write raises, the temp
  file is unlinked.
- **Tier policy is preserved.** `patch_file` enforces the same
  restricted-tier upload read-only block as `write_file` (M8).
  The agent can patch a `.smolcode/uploads/*` file only at the
  elevated tier; the restricted tier raises `PermissionError`.
- **Audit events are recorded.** Every diff gate decision emits a
  `diff_decision` audit event via `run.audit_sink.record(...)` with
  `tool`, `path`, `summary`, `approved`, `reason`, `edited`,
  `run_id`. This mirrors the M9 `destructive_decision` event so
  the existing audit viewer (M8) can show diff approvals next
  to destructive approvals.
- **No diff payload leakage in stderr.** The diff is built inside
  the runner; it is published to the SPA via SSE and to the audit
  log. It is NOT printed to the agent's stderr (which would
  pollute the LLM context) — the diff callback catches any
  `diffs.compute` exception, falls back to an empty payload, and
  logs a warning instead of letting the exception propagate.
- **The DiffViewer is a CSS-only renderer.** It does NOT execute
  the diff content as code or HTML. Every line is rendered via
  React text nodes; the raw `before` / `after` strings are
  displayed in a `<pre>` with `spellCheck={false}` only when the
  user explicitly toggles "Show original".
- **Timeout behaviour matches M9.** Default 30 s; on timeout the
  gate returns `DiffDecision(approved=False, reason="timeout")`,
  the tool raises `PermissionError`, the agent sees the failure
  in `step.action.observations`, and the SSE stream emits
  `diff.resolved` with `reason="timeout"`.

**Known limitations (M10)**

- **No diff for binary files.** `_apply_unified` works on UTF-8
  text only; binary writes via `write_file(path, bytes)` would
  bypass the diff gate entirely because smolagents' Tool
  serialisation requires string args. This is intentional for M10
  (no agent should be writing binaries anyway); a future
  `write_bytes` tool would need its own policy.
- **Edit-then-approve can introduce invalid content.** The
  user-supplied `edited_after` is NOT re-validated against any
  schema or pre-image. The trust model is: the user is the
  ground truth. If they want to write garbage to the file, that
  is their call. The audit log captures the edit so a reviewer
  can spot it later.
- **Workspace tree can be slow on huge repos.** The walk is
  bounded (5000 entries / 10 levels by default) but the call
  itself is O(N). The SPA polls every 10 s; very large
  workspaces may want to lower the interval or raise
  `max_entries`. v1.1 followup: cache the tree and re-walk only
  on mtime change.
- **No side-by-side diff view.** The M10 viewer is a unified
  inline diff (added on green, deleted on red, context on white).
  A side-by-side mode is a v1.1 followup.

**Out of scope (v1.1+)**

- Side-by-side diff mode.
- Syntax-highlighted diff (the language is unknown to the
  runner; the SPA could infer from the file extension).
- Comment / review on diff hunks (GitHub-style).
- Diff for MCP tool output payloads (covered by M11 inline
  preview).
- Per-file diff policy (e.g. allow `*.md` to skip the gate,
  require `*.py` to always gate). v1.1 followup.

## 9. Kernel-level network enforcement for elevated tier (M16, decision 0020)

### 9.1 Why this exists

v1.0's elevated tier was declared "restricted" network but the
container actually ran with `network_mode=none` (same as restricted);
the `network_allowlist` data structure was wired but never enforced.
M16 closes that gap by enforcing the allowlist **at the kernel level**
inside the elevated container.

This is defense-in-depth. Even if a Python-level `safe_shell` allowlist
or the `LocalPythonExecutor` imports check is bypassed, packets are
still dropped at the network stack unless they target an explicitly
allowlisted CIDR.

### 9.2 Container boot sequence

The elevated image's ENTRYPOINT is `/usr/local/bin/iptables-init.sh`
(see `smolcode/src/smolcode/docker/`). The script runs as root
inside the container (iptables requires `CAP_NET_ADMIN`), applies the
firewall, then drops to UID 1000 (smolagent) via `gosu` before
exec'ing the agent process. The agent itself never sees
`CAP_NET_ADMIN`.

The init script:

1. **Default-deny OUTPUT** — `iptables -P OUTPUT DROP`
2. **Loopback ACCEPT** — needed for inter-process comms and the
   jupyter kernel socket
3. **DNS ACCEPT to each nameserver in `/etc/resolv.conf`** — parsed
   at init time so it works on both Linux Docker (`127.0.0.11`)
   and Docker Desktop / other hosts (e.g. `192.168.65.7`)
4. **ESTABLISHED/RELATED ACCEPT** — return traffic for the DNS
   flows
5. **Per-CIDR ACCEPT** — one rule per entry in
   `ELEVATED_NET_ALLOWLIST`
6. **Validate CIDRs first** — using `python3 -c "ipaddress.ip_network(c, strict=False)"`
   to match the Python-side validator. On the first invalid CIDR,
   the script exits 78 (EX_CONFIG) without applying any allowlist
   rules (fail-closed)
7. **Drop to UID 1000** via `/usr/local/bin/gosu 1000:1000 "$@"`

### 9.3 Schema semantics

`Tier.network_allowlist` is a tuple of **CIDR strings** (e.g.
`"140.82.112.0/24"`), not hostnames. The v1.0 hostname form had no
consumers and was never enforced; the M16 rename is documented in
`config.py` and is non-breaking (no code in v1.0 ever set the
field to a hostname and depended on it being enforced).

If an operator needs a hostname in their allowlist, they must
resolve it themselves (e.g. via `dig +short example.com` or
`nslookup`) and supply the resulting CIDR. DNS resolution is
intentionally out of scope for M16 because resolution races (an
agent could trigger a different DNS resolution at request time vs.
rule application time) would weaken the guarantee.

### 9.4 Operator-supplied configuration

`smolcode` populates the env-var dict via
`smolcode.container.elevated_container_env(tier)`. The helper
validates each CIDR via `ipaddress.ip_network(strict=False)` and
raises `ConfigError` on the first malformed entry — fail-closed
BEFORE the container is launched.

Operators can also bypass `smolcode` entirely by setting
`ELEVATED_NET_ALLOWLIST` directly on the container (e.g. for
`docker run` experimentation).

### 9.5 Kill switch (ELEVATED_DISABLE_IPTABLES)

A container env var `ELEVATED_DISABLE_IPTABLES=1` causes the init
script to skip firewall setup entirely. The script logs a WARN to
stderr; the agent process runs with no kernel-level network
restriction.

This is a **security-sensitive escape hatch** for emergency debugging
(e.g. "the firewall rules are wrong and I need to debug the agent
ASAP"). It is **not** the default; `smolcode` never sets this
variable itself. Operators who set it should also document why
they did so in their run logs.

When the kill switch is active, the firewall setup is bypassed but
`smolcode` (the Python side) still validates the CIDR list via
`parse_cidr_allowlist` before launching the container, so a
malformed allowlist is still caught at container-launch time.

### 9.6 Capability requirements

The elevated container must be launched with `cap_add=["NET_ADMIN"]`.
`smolcode` adds this automatically in
`agents/base.py:_executor_kwargs_for` (elevated tier only). Without
`NET_ADMIN`, the iptables commands fail with "Permission denied" and
the init script exits non-zero. `smolcode` does **not** add
`NET_ADMIN` to the restricted or full_access containers.

The `NET_ADMIN` cap is held only by the init script's brief window
as PID 1. After `gosu` drops privileges, the agent process has no
`NET_ADMIN` (Linux drops capabilities on `setuid` unless
`capabilities: ["NET_ADMIN"]` is added to the container; we don't
do that, so the cap is gone by the time the agent runs).

### 9.7 Known limitations

- **IPv6 is dropped.** v1.7 ships v4-only. The elevated container's
  `ip6tables` OUTPUT policy is unchanged (typically ACCEPT by
  default), but since the v4 OUTPUT chain drops everything except
  allowlisted v4 CIDRs, and DNS AAAA queries still happen, an
  agent could theoretically still leak v6 metadata via DNS. IPv6
  support is a v1.8 candidate (decision 0021).
- **No per-process filtering.** The firewall applies to ALL processes
  in the container, not just UID 1000. A v1.9 candidate adds
  `--uid-owner` filtering.
- **CAP_NET_ADMIN after firewall setup is not dropped.** The init
  script drops UID via `gosu` but the container's
  `capabilities` list still includes `NET_ADMIN`. A future v1.8
  improvement is to use `cap_drop=["NET_ADMIN"]` after the
  firewall is configured (mitigates R-M16-H).
- **Container-internal only.** The host's network namespace is
  untouched. `smolcode` does not require `CAP_NET_ADMIN` on the
  host.

### 9.8 Test coverage

The unit tests in `smolcode/src/smolcode/tests/test_elevated_iptables.py`
(19 tests, always run) cover:

- CIDR parsing (basic, empty, whitespace, trailing comma, IPv6, invalid)
- Format/parse round-trip
- `elevated_container_env` for the elevated tier (default, with
  allowlist, invalid CIDR, wrong tier)
- Kill-switch detection (truthy "1" only; "true"/"yes"/"on" ignored)

The contract tests gated on `@pytest.mark.docker` (4 tests) cover:

- Default-deny: curl to a public IP times out
- Fail-closed: malformed CIDR makes the container exit non-zero
- Allowlist + kill switch: skipped when the host can't reach the
  public internet from containers (a Docker Desktop networking
  limitation; not an M16 issue)
- Shellcheck: `iptables-init.sh` lints clean under shellcheck
  (skipped when shellcheck is not installed)

**v1.7 firewall-status invariants:**

- Empty `network_allowlist` → container has loopback + DNS egress
  only (no external connectivity)
- Populated `network_allowlist` → loopback + DNS + each CIDR
- Malformed CIDR → container exits 78, agent never starts
- `ELEVATED_DISABLE_IPTABLES=1` → no firewall; agent runs with
  unrestricted egress (kill switch)


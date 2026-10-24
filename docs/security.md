# Security Model

**Date:** 2026-10-24 (re-verified claim by claim; originally written 2026-06-28)
**Author:** Phase 9 documentation alignment (decision 0044); original planning pass 2026-06-28
**Status:** active
**Related:** `docs/environment.md`, `docs/architecture.md`, `docs/roadmap.md`

> **How to read this (2026-10-24).** Every claim below that names code was
> re-checked against the tree at `7ba1705`; where the implementation and this
> document disagree, the code wins and this file is the bug (decision 0044 §1).
> Claims that need a live Docker daemon or a provider key are marked *(not
> verified on this host: daemon down, no keys)*; host facts live in
> `docs/environment.md`. Section numbers are stable identifiers referenced from
> decisions and `README.md`, so they were not renumbered wholesale. The one
> exception: the kernel-enforcement block at the end of this file used to be a
> second `## 9.` heading; it is now §16 (matching milestone M16) and its
> subsections are 16.1–16.8, while the audit log keeps §9. References from
> ADRs 0020/0034 to the old §9.5 are historical; live references were updated
> (decision 0044 §2). Sections 3.5, 3.6 and 16 keep their original numbers but
> sit at the end of the file because they were appended after §12; the numbers,
> not the order, are the stable identifiers.

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
   and is explicitly labelled "not a sandbox" in the CLI. `docker` is the
   default executor. On the 2026-10-24 verification host the daemon is NOT
   running (`docker info` exits 1), so no sandbox claim in this document was
   executed here and `smolcode web` fails closed at startup; the `local`
   fallback is for development only and says out loud that it is not a sandbox.
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
| Python imports | `json`, `pathlib`, `ast`, `textwrap`, `re`, `typing`, `dataclasses` (7 names) | Anything else → `additional_authorized_imports` rejects. No `os`, no `sys`, no `subprocess`, no network modules. |
| Shell commands | `python`, `pytest`, `git`, `ruff` (4 names) | `shell.run` basename allowlist; `subprocess.run(shell=False)` always. `cat`/`head`/`grep`/`find` are **not** commands in this tier — file reads go through `read_file`, which applies `PathPolicy`. |
| Network | **none** | The container attaches only to the internal bridge `smolcode-internal`, which has no default route (Phase 1/H1); `Tier.network` is `"none"` and no `iptables` init runs. |
| MCP servers | the operator's per-server `allow` list | `tool_is_allowed()` — **default-deny**, so a server with no `allow` exposes nothing. *(Changed in Phase 6 / ADR 0041. The previous control was a `^(get\|search\|read\|list)_` name-prefix regex. The name is chosen by the MCP server — the untrusted side of the boundary — so a destructive tool named `get_nuke` satisfied it. The regex was deleted rather than kept as a second gate.)* |
| `max_steps` | 12 | Bounds compute + LLM cost (`Tier.max_steps`). |
| Wall-clock timeout | per-command 120 s | `Tier.timeout_s=120` is the **ceiling for one `run` call** (`run` clamps a larger model-supplied timeout down to it), not a cap on the whole run: there is no wall-clock limit on `agent.run()` in the CLI and `asyncio.wait_for` is not used there. Web-started runs are killed after `SMOLCODE_WEB_RUN_TIMEOUT_S` (default 900 s) instead. |

### 3.2 Elevated (opt-in, used for tasks like "open a PR")

**Trust assumption:** the user has authorised the agent to perform
network-bounded actions (push to a remote, open a ticket) that the
restricted tier cannot. Elevated is **not** an "anything goes" tier; it
is "network + the tools needed for code review and deployment prep".

| Capability | Allowed? | Notes |
|---|---|---|
| Filesystem | workspace only | `Tier.paths` is empty for every shipped tier and the fs tools do not consult it. Specialist `extra_paths` metadata is recorded but **not enforced today** (known limitation, see §5.3). |
| Python imports | restricted ∪ `collections`, `itertools`, `functools`, `os`, `sys`, `tempfile`, `hashlib`, `shutil`, `glob` (16 names) | `socket`, `http`, `urllib`, `subprocess`, `ssl`, `ctypes` are **not** authorized — the agent reaches the network only through `curl`/`pip` subprocesses, if the allowlist admits them. |
| Shell commands | restricted ∪ `pip`, `npm`, `node`, `curl`, `jq`, `make` (10 names) | Basename allowlist. There is no `pnpm`, no `cargo`, and no read-only `docker` client, contrary to earlier drafts. |
| Network | CIDR allowlist in `Tier.network_allowlist` (empty by default) | Kernel-enforced since v1.7/v1.8 by `docker/iptables-init.sh` (decision 0020; IPv6 since decision 0034). Empty default = loopback + Docker DNS only, i.e. **no egress**. See §7.2 and §16. |
| MCP servers | only tools named in each server's own `allow` list | Default-deny per server. There is no name-pattern filter and no "readwrite" blanket; the allowlist is the boundary (Phase 6 / ADR 0041). |
| `max_steps` | 20 | `Tier.max_steps`. |
| Wall-clock timeout | per-command 180 s | `Tier.timeout_s=180` caps one `run` call; there is no whole-run wall clock in the CLI (see §3.1). |

### 3.3 Full-access (explicit, audited)

**Trust assumption:** the user has set up a specialist agent for a
narrow, well-understood workflow (deploy to staging, run a data
pipeline, push a release branch). The agent runs **only** if invoked
explicitly (`--tier full_access`) and **only** after a per-run
confirmation prompt (`Confirm full-access run? [y/N]`). Every
full-access run writes an `AuditEntry` to `logs/audit.jsonl`.

| Capability | Allowed? | Notes |
|---|---|---|
| Filesystem | workspace only | Same boundary as restricted/elevated. Full access is wider in *commands, imports and network*, not in filesystem roots. |
| Python imports | elevated ∪ `subprocess`, `threading`, `multiprocessing`, `asyncio`, `socket`, `http`, `http.client`, `urllib`, `urllib.parse`, `urllib.request`, `ssl`, `smtplib`, `secrets`, `base64`, `sqlite3`, `csv`, `configparser`, `xml`, `xml.etree`, `pickle`, `ctypes` (37 names total) | `requests`, `httpx` and `paramiko` are **not** authorized (the tier already has `urllib` + sockets). `pickle`/`ctypes` are deliberately allowed: this tier is the one that can do real damage and is audited as such. |
| Shell commands | elevated ∪ `ssh`, `scp`, `rsync`, `docker`, `kubectl`, `terraform`, `ansible`, `aws`, `gcloud`, `az` (20 names) | `helm` is **not** in the allowlist. These binary names are also classified as destructive by the gate, so they need an approved policy (see the A3 note below). |
| Network | open | `Tier.network="open"`, `network_allowlist=("*",)`: the Docker default bridge with no `iptables` init (that runs for elevated only). |
| MCP servers | only tools named in each server's own `allow` list | Same default-deny rule; there is no "full set" bypass. |
| `max_steps` | 40 | `Tier.max_steps`. |
| Wall-clock timeout | per-command 300 s | `Tier.timeout_s=300` caps one `run` call; the whole-run wall clock exists only in the web runner (900 s default). |

**Known limitation — destructive approval (A3, ADR 0041).** The host-side
approval path works when the tool body runs on the host (`SMOLCODE_EXECUTOR=local`,
or MCP tools). Under the **default Docker executor**, smolagents
serialises the tool source into the container, where `smolcode.session` does
not exist: the in-container path cannot reach `SessionState.confirm_callback`
and can only consult the policy bound at build time. That policy is `deny`
unless the session was already auto-approved when `build_tools()` ran, so
in-container destructive calls are **refused, not prompted** (fail-closed).
Consequence: `--auto-approve-destructive` and the web approval modal do not
authorize a destructive command executed inside the Docker sandbox today. A
host-side approval broker that ships decisions into the container is not
built. Do not weaken the gate to make the modal work; ADR 0041 records the
options considered.

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
Deletion is always explicit: per-file button in the GUI (`DELETE
/api/uploads/{name}`), or `smolcode uploads clean [--older-than N] [--yes]`
for bulk. There is **no** `smolcode uploads delete` verb — the CLI exposes
`uploads path|list|clean` only. Every upload and delete emits an `upload.add` /
`upload.delete` event in the audit log so the trail is complete.

The full upload design is in `docs/decisions/0010-gui-design.md` D8.

---
## 4. Layered controls

Even within a tier, multiple independent layers must be bypassed for a
genuine escape. The layers, as actually implemented (innermost first):

```
+--------------------------------------------+
| 1. Container boundary (Linux; the tier     |
|    image sets a non-root user)             |
| 2. Network topology (internal bridge /     |
|    iptables CIDR allowlist / open bridge)  |
| 3. Runtime resource ceilings (mem_limit,   |
|    pids_limit, nano_cpus - Phase 8/0043)   |
| 4. additional_authorized_imports           |
|    (smolagents LocalPythonExecutor)        |
| 5. PathPolicy (realpath + commonpath       |
|    workspace boundary on the fs tools)     |
| 6. Command allowlist (basename match in    |
|    shell.run; argv-only, shell=False)      |
| 7. Tier policy in config.py                |
|    (Settings + Tier dataclasses)           |
| 8. max_steps (CodeAgent built-in)          |
| 9. Audit logging (all tiers by default)    |
| 10. Approval gates (host plane only;       |
|     see the A3 limitation in section 3.3)  |
+--------------------------------------------+
```

**Corrections from the 2026-06-28 draft (decision 0044):** smolcode does
**not** pass `cap_drop=ALL`, a read-only root filesystem, or tmpfs mounts to
`docker run` — those layers were aspirational, and no wall-clock watchdog is
applied to `agent.run()` in the CLI. What exists is the container boundary
plus the network topology, the Phase 8 runtime ceilings, and the
Python/tool-level policy. The tier images define their own non-root user;
tightening the images themselves is Phase 8 scope (`docker/*.Dockerfile`).

The load-bearing boundary is the container (layers 1-3). If layer 4 is
bypassed, layers 1-3 still constrain what the code can do; if the `local`
executor is used instead, layers 1-3 are gone by definition and the CLI says
so. No single *Python-level* bypass escapes the sandbox — but the sandbox is
the thing that has to hold.
---

## 5. Path policy

The fs tools (`read_file`, `write_file`, `patch_file`, `list_dir`) are the
gate for every filesystem operation the model can perform. In
`src/smolcode/tools/fs.py` they:

1. **Contain the path in the workspace.** Every path is resolved with
   `os.path.realpath()` and compared with the realpath of the workspace via
   `os.path.normcase()` + `os.path.commonpath()`; when the common prefix is
   not the workspace they raise `PermissionError("path resolves outside
   workspace")`. This is not a lexical `..` filter — resolution follows
   symlinks and junctions (case-insensitively on Windows), so `..` and
   symlink escapes are handled by resolution itself.
2. **Re-check after resolution.** Each call resolves twice and compares the
   results (`"path changed during resolution"`), a cheap defence against a
   symlink swapped between the check and the use.
3. **Workspace only — no per-tier extra paths.** `Tier.paths` exists but is
   empty for `restricted`, `elevated` and `full_access`, and no tool reads
   it. Specialist agents may declare `extra_paths` in `agents.toml`; that
   value is parsed and stored, but **no policy enforces it today** (known
   limitation, Phase 7/8 scope). The earlier claims about enforced
   `extra_paths` were false.
4. **Read-only uploads at restricted tier.** The `<workspace>/.smolcode/uploads`
   subtree is mounted `ro` into the restricted container (Phase 6, decision
   0041), and `write_file`/`patch_file` additionally raise on that path at
   the restricted tier. There is no other `:ro` mount and no hash attestation.
5. **No SHA-256 write attestation.** Uploads record a SHA-256 in their
   sidecar metadata, but host file writes are not hashed or signed. The
   previous claim here was aspirational and has been removed.

---

## 6. Command policy

The `shell.run` tool's contract (`src/smolcode/tools/shell.py`):

- **No `shell=True`.** Always `subprocess.run([cmd, *args], shell=False)`;
  `test_security.py::test_shell_run_uses_shell_false` pins this from the
  source.
- **Basename allowlist on `cmd` only.** `cmd` is a single executable name
  (there is no tokenisation — passing arguments inside `cmd` fails the
  basename check); its basename, after stripping a Windows `.exe/.bat/.cmd/
  `.com` suffix, must equal an entry in `Tier.commands`. No regex, no
  `startswith`.
- **Args are strings, never shell syntax.** `args` must be a list and every
  element a string, otherwise `PermissionError`. `;`, `&&`, `|`, `>`, `<`
  are passed through as **literal argv**, because there is no shell to
  interpret them (`test_shell_run_metachars_are_literal_args`). `..` in an
  argument is likewise not rejected lexically; the allowlist stops the agent
  from choosing a binary such as `cd` that would interpret it.
- **Timeout.** Every `subprocess.run` gets a `timeout`; it defaults to 60 s,
  must be positive, and is clamped down to `Tier.timeout_s` (120/180/300 s)
  when the model asks for more.
- **Output is captured and truncated.** `stdout`/`stderr` are returned as
  text with a 1 MiB per-stream cap and an explicit `...[TRUNCATED ...]`
  marker, so a chatty command cannot flood the model context.
- **No backgrounding.** `&` is only ever a literal argument, and `nohup` is
  not in any tier's command allowlist.



---

## 7. Network policy

### 7.1 Restricted tier

Container attaches **only** to the internal Docker bridge
`smolcode-internal` (`smolcode.container.INTERNAL_NETWORK_NAME`), created
without a default route; no `iptables` rules are involved. `Tier.network`
is `"none"`. The container cannot call out, phone home, or resolve DNS; the
topology enforces it (Phase 1/H1).

### 7.2 Elevated tier

The allowlist is a tuple of **CIDRs**, not hostnames, enforced at the kernel
level since v1.7 (decision 0020; IPv6 since v1.9/decision 0034). The
container's ENTRYPOINT `docker/iptables-init.sh` runs as root with
`CAP_NET_ADMIN`, applies default-deny OUTPUT chains on `iptables` **and**
`ip6tables`, accepts loopback + Docker DNS, accepts one rule per allowlisted
CIDR (classified by family in `smolcode.container.classify_cidrs`), then
`exec`s `gosu 1000:1000` so the agent process never holds `CAP_NET_ADMIN`.
An empty allowlist is legal and is the default: it yields loopback + DNS and
**no egress**. A malformed CIDR fails closed (exit 78) before any partial
rules are applied, and the Python side rejects it earlier still in
`elevated_container_env()`. Full mechanics and the kill switch are in §16.

### 7.3 Full-access tier

`Tier.network="open"` with `network_allowlist=("*",)`: the container joins
the Docker default bridge with unrestricted egress. No `iptables` init runs
for this tier (it is elevated-only). Still never `network_mode="host"` —
that would bypass container isolation entirely, and smolcode never sets it.

### 7.4 Outbound MCP servers

MCP servers reachable over `streamable-http` are subject to the
same network policy as any other outbound call. An MCP server that
the tier's network policy rejects cannot be reached, even if its URL
is configured.

### 7.5 MCP is not sandboxed (R13, decision with operator 2026-09-24)

**The docker executor sandboxes model-written CODE. It does not sandbox MCP
TOOL CALLS.** An MCP tool call executes on the host, in the MCP server process,
outside every container. If the model can call a tool, the model can reach
whatever that tool reaches — regardless of `SMOLCODE_EXECUTOR=docker`.

This is a difference of **location**, not of permission. The allowlist,
environment floor, and destructive gate all still apply; none of them move the
execution. Nothing in the container boundary covers it.

**It is refused by default.** Under `SMOLCODE_EXECUTOR=docker`, a run with any
MCP server configured and without an explicit opt-in will not start those
servers:

| Executor | MCP configured | Opt-in | Result |
|---|---|---|---|
| `docker` | yes | no | **refused** — run does not start |
| `docker` | yes | yes | allowed; a `NOTICE: MCP TOOLS ARE NOT SANDBOXED` banner is printed to stderr at start |
| `local` | yes | n/a | allowed; the existing `NOT SANDBOXED` banner already covers the whole run |
| any | no | n/a | unaffected |

Opt in with `--allow-unsandboxed-mcp` or `SMOLCODE_ALLOW_UNSANDBOXED_MCP=1`.

**Why a refusal and not a warning.** The path is reachable by default — any
server in `mcp_config.json` — so a banner on that path prints on every run and
is scrolled past. A control that fires every time and is ignored every time is
indistinguishable from no control. Refusing converts a silent risk into a
loud one, and the operator's only remedy is a deliberate flag.

**This is not a sandbox.** The flag accepts the capability; it does not contain
it. Running MCP servers in their own containers behind a narrow host-side
bridge remains unbuilt — see R13 in the review report for the honest scope.

Other hardening that does apply to MCP: per-server `allow` (default-deny),
the environment floor, unique server ids, an enforced `timeout_s`, and the
destructive gate for tools whose names read as destructive.

---

## 8. Secrets policy

| Concern | Mitigation |
|---|---|
| API key in source | None. We refuse to merge any commit containing a key matching `sk-`, `sk-ant-`, `hf_`, `ghp_`, `gho_`, `ghu_`, `ghs_`, `AIza*`, `AKIA*`, etc. (M7 + M13 prefixes, see `smolcode/redact.py:DEFAULT_PATTERNS`; `SEC-18` pattern from sibling project). |
| API key in `.env` | `chmod 600`, gitignored, never logged. |
| API key in CLI args | `--api-key` is **not** a flag. Keys come from env only. |
| API key in process env of the agent container | smolcode passes an `environment` dict only for the elevated tier (allowlist + kill switch, decision 0020); for every tier smolagents' `DockerExecutor` adds `KG_AUTH_TOKEN` and the image default `PATH`. No provider key is ever placed in that dict: model calls are made from the host process, not the container. This is reviewed code, not a pinned test. |
| Key leak via structured logs | A single `RedactSecretsFilter` redacts values matching its **9 prefix families** — `sk-ant-…`, `sk-…`, `hf_…`, `ghp_…`, `gho_…`, `ghu_…`, `ghs_…`, `AIza…`, `AKIA…` — before log emission (M7 + M13; canonical list in `smolcode/redact.py:DEFAULT_PATTERNS`). Generic `KEY=` / `TOKEN=` assignment shapes are deliberately NOT matched (over-redaction risk); adding a family requires updating this row plus `test_redact.py`. Reconciled with the implementation in Phase 2 (the previous wording claimed a `*KEY=*...` rule that never existed). |
| Key in crash dump | The CLI catches exceptions and emits a structured error; raw tracebacks are not printed when a key is in `os.environ`. |
| Web UI traceback leak (decision 0024) | `agent_runner.run_in_thread`'s broad `except Exception` block now appends `traceback.format_exc()` to `run.error` AND surfaces it in the `EVT_ERROR.traceback` SSE field. The `RedactSecretsFilter` is applied to all SSE events before publish (per `web/api.py` + `redact.py`), so any API key, OAuth token, or env-var value that lands in a traceback frame variable name is scrubbed before it leaves the server. Capped at 8 KB so a runaway traceback cannot blow up the SSE queue. |
| Provider response caching | LiteLLM's `caching` plugin is **off** by default. Enabling it stores API responses on disk and could leak data across runs. |
| Token usage surfaced in CLI | `TokenUsage` is shown on stderr; the model answer is printed to stdout and is **not** persisted by default. There is no `--save-run` flag (it never existed) — the durable record is the audit log, which stores run metadata and gate decisions, not the answer text. |

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

Every smolcode run writes to `logs/audit.jsonl` (one JSON object
per line): CLI runs via a per-run sink, web-started runs via the
per-app sink built when the server boots (Phase 2/H5 — previously
web runs produced **zero** audit records). Pass `--no-audit` (CLI,
or `smolcode web`) to opt out entirely.

As of **M13** every line also carries a SHA-256
hash chain (`prev_hash` + `entry_hash`) so silent tampering with
prior entries can be detected by replay. Use `smolcode audit verify`
to confirm chain integrity (CI-friendly; exit 0 = clean, exit 1 =
tampered/unverifiable). See `docs/decisions/0016-m13-audit-integrity-redact-expansion.md`
for the chain construction and `smolcode/src/smolcode/audit.py:verify_chain`
for the verifier. The chain is **on by default**; set
`SMOLCODE_AUDIT_HASH_CHAIN=0` to disable it (not recommended). Any other value
leaves it enabled: the flag is parsed as a boolean, so `=1` keeps the chain on.

Phase 2 chain semantics across runs: each new sink **continues**
the chain found at the end of the log file, so legitimate multi-run
logs (the normal CLI case — every run appends to the same file)
pass `verify_chain` end-to-end. Appending to a log whose last entry
FAILS verification is refused (`AuditError`) so a tampered tail can
not be silently laundered by further writes; rotate or restore first.

Each entry contains:

```jsonc
{"ts": "2026-10-24T14:33:01Z", "event": "start", "pid": 12345,
 "tier": "full_access", "task": "deploy commit abc123 to staging",
 "model": "MiniMax-M3", "provider": "minimax", "executor": "docker",
 "workspace": "E:\\python_projects\\smol_code\\workspace"}
{"ts": "...", "event": "step", "pid": 12345, "step": 3, "action": "shell.run"}
{"ts": "...", "event": "end", "pid": 12345, "exit_code": 0, "duration_s": 47.2}
{"ts": "...", "event": "error", "pid": 12345, "kind": "PermissionError",
 "message": "destructive run blocked: docker (policy='deny')"}
```

Gate and integration events add their own fields on the same shape:
`destructive_decision` (`tool`, `summary`, `approved`, `reason`,
`auto_approve_now`, `auto_approve_off`), `diff_decision` (`tool`, `path`,
`summary`, `approved`, `reason`, `edited`, `run_id`), `upload.add` /
`upload.delete`, `checkpoint`, `subagent`, `full_access_confirmed`. When the
hash chain is on, every line additionally carries `prev_hash` and
`entry_hash` (64 hex chars each).

The audit log is **append-only** (write mode `'a'`, never `'w'`)
and rotates via `smolcode audit rotate --keep-days N` (M14.3,
decision 0018). The CLI verb pre-verifies the chain and **refuses
to rotate a tampered log** (exit code 4), so a broken chain is
never silently gzipped and held forever. The standalone
`scripts/rotate_audit_log.py` predates this guarantee; prefer the
CLI verb for any new deployment.

**Volume note (reconciled in Phase 2):** contrary to earlier drafts,
ALL tiers are audited by default today — restricted included — because
per-run records are cheap (start/end/error plus gate decisions, not
per-token dumps). Rotation (`smolcode audit rotate --keep-days N`)
keeps the live log bounded; a separate `INFO` log still captures
everything at the user's option via `SMOLCODE_LOG_LEVEL=DEBUG`.

Operators read the log four ways (all apply `RedactSecretsFilter`
so leaked keys cannot escape — including `audit ls --json` since
Phase 2; suppress with `--no-redact` when you genuinely need raw
fields):

- `smolcode audit ls [-n N] [--json]` — quick terminal scan
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
| Run arbitrary binary | Y (container boundary; non-root image user) | n/a | Y | n/a | n/a | Y | Y | logged |
| Install pip package | Y | n/a | Y (allowlist) | Y (elevated needs a pypi CIDR in the allowlist; empty default blocks it) | n/a | Y | Y | logged |
| Open outbound socket | Y (network_mode) | n/a | n/a | Y | n/a | n/a | n/a | logged |
| Import `os`, `subprocess` | n/a | n/a | n/a | n/a | Y | n/a | n/a | n/a |
| Import `ctypes`, `importlib` | n/a | n/a | n/a | n/a | Y | n/a | n/a | n/a |
| Loop forever | Y (pids_limit, Phase 8 default 256/512) | n/a | n/a | n/a | n/a | Y | Y | logged |
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

Security is not a separate suite that can quietly rot: the controls above are
pinned by tests that fail when the implementation and this document disagree.

1. **Static:** `ruff check` + `ruff format --check` on every changed file (CI
   `lint` job, `make quality`).
2. **Unit + integration:** `pytest` across `smolcode/src/smolcode/tests/`. CI
   enforces `--cov-fail-under=80` in the blocking `coverage` job; the coverage
   flags live in `Makefile`, not `pyproject.toml`.
3. **Security tests** (`tests/test_security.py`, 26 test cases):
   - Tier policy cannot be downgraded by env var (`SEC-2`); `SMOLCODE_TIER` is
     deliberately not honoured.
   - `shell.run`: `args` must be a list of strings; a `cmd` basename outside
     the allowlist is rejected; `shell=False` is asserted from the source;
     `;`, `&&`, `|`, `>` are passed as literal argv (no shell exists to
     interpret them). `..` in an argument is *not* rejected lexically — path
     safety belongs to the fs tools' `PathPolicy`, and the command allowlist
     stops the agent from selecting a binary such as `cd` that would
     interpret it.
   - `PathPolicy` rejects symlink escapes, `..` traversal and absolute paths
     outside the workspace.
   - MCP tools are exposed only when named in the per-server `allow` list;
     allowlisted names that read as destructive are still gated; shadowed
     names are rejected.
   - `RedactSecretsFilter` covers all nine prefix families in messages,
     format strings and exception text.
   - `AuditSink` rejects write mode `'w'` and accepts append modes.
   - Per-tier baselines: restricted has no `os`/`sys`/`subprocess`, elevated
     adds no `socket`/`http`, full_access is the only open-network tier.
4. **Smoke:** `--smoke` forces the `local` executor and a stub model, then
   runs the selected tier once offline. It is not a per-tier matrix.
5. **Container contract:** the Docker-gated tests in §16.8 are the only place
   the firewall and executor boundary are executed; they skip when no daemon
   is available, which is why CI runs them on the Docker job.

Known gap: nothing asserted that *this document* matched the code until the
textual docs-guard CI job added by decision 0044 §8.
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

## 16. Kernel-level network enforcement for elevated tier (M16, decision 0020)

> **Renumbered in Phase 9 (decision 0044 §2):** this block used to be a second
> `## 9.` heading, colliding with §9 (audit log). It is §16 now, matching
> milestone M16, and the subsections moved with it (9.x → 16.x). ADRs 0020 and
> 0034 cite the old numbers, which is correct for those historical records.

### 16.1 Why this exists

v1.0's elevated tier was declared "restricted" network but the
container actually ran with `network_mode=none` (same as restricted);
the `network_allowlist` data structure was wired but never enforced.
M16 closes that gap by enforcing the allowlist **at the kernel level**
inside the elevated container.

This is defense-in-depth. Even if a Python-level `safe_shell` allowlist
or the `LocalPythonExecutor` imports check is bypassed, packets are
still dropped at the network stack unless they target an explicitly
allowlisted CIDR.

### 16.2 Container boot sequence

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

### 16.3 Schema semantics

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

### 16.4 Operator-supplied configuration

`smolcode` populates the env-var dict via
`smolcode.container.elevated_container_env(tier)`. The helper
validates each CIDR via `ipaddress.ip_network(strict=False)` and
raises `ConfigError` on the first malformed entry — fail-closed
BEFORE the container is launched.

Operators can also bypass `smolcode` entirely by setting
`ELEVATED_NET_ALLOWLIST` directly on the container (e.g. for
`docker run` experimentation).

### 16.5 Kill switch (ELEVATED_DISABLE_IPTABLES)

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

### 16.6 Capability requirements

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

### 16.7 Known limitations

- **IPv6 is enforced since v1.9 (decision 0034).** Both `iptables` (v4) and
  `ip6tables` (v6) get default-deny OUTPUT chains, loopback + Docker DNS
  accepts, and one ACCEPT per allowlisted CIDR (classified by address family
  in `smolcode.container.classify_cidrs`). This closes the v1.7 gap where the
  v6 policy stayed ACCEPT while the docs claimed it was dropped. The kill
  switch `ELEVATED_DISABLE_IPTABLES=1` disables **both** chains.
- **No per-process filtering.** The firewall applies to ALL processes in the
  container, not just UID 1000; a `--uid-owner` refinement remains a
  candidate (decision 0020 risk register).
- **`CAP_NET_ADMIN` is gone after setup.** The init script runs as PID 1
  while the container holds `NET_ADMIN`, applies the rules, then `exec`s
  `gosu 1000:1000`; Linux clears the capability set on the UID change and
  smolcode does not re-add it. The v1.7 wording that claimed the cap survived
  into the agent process was wrong.
- **Container-internal only.** The host's network namespace is untouched.
  `smolcode` does not require `CAP_NET_ADMIN` on the host.

### 16.8 Test coverage

The unit tests in `smolcode/src/smolcode/tests/test_elevated_iptables.py`
collect **33 tests**: 28 always run, 4 are gated on `@pytest.mark.docker`
and 1 on `@pytest.mark.shellcheck`. The always-run set covers:

- CIDR parsing (basic, empty, whitespace, trailing comma, IPv6, invalid)
- Format/parse round-trip
- `elevated_container_env` for the elevated tier (default, with
  allowlist, invalid CIDR, wrong tier)
- Kill-switch detection (truthy "1" only; "true"/"yes"/"on" ignored)

The contract tests gated on `@pytest.mark.docker` (4) and `@pytest.mark.shellcheck` (1) cover:

- Default-deny: curl to a public IP times out
- Fail-closed: malformed CIDR makes the container exit non-zero
- Allowlist + kill switch: skipped when the host can't reach the
  public internet from containers (a Docker Desktop networking
  limitation; not an M16 issue)
- Shellcheck: `iptables-init.sh` lints clean under shellcheck
  (skipped when shellcheck is not installed)

**Firewall-status invariants (v1.7, extended to IPv6 by decision 0034):**

- Empty `network_allowlist` → container has loopback + DNS egress
  only (no external connectivity)
- Populated `network_allowlist` → loopback + DNS + each CIDR
- Malformed CIDR → container exits 78, agent never starts
- `ELEVATED_DISABLE_IPTABLES=1` → no firewall; agent runs with
  unrestricted egress (kill switch, both families)
- Both invariants hold for v4 **and** v6 chains since decision 0034


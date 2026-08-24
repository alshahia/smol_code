# 0006 — M4: elevated + full_access tiers

**Date:** 2026-08-19
**Status:** active
**Supersedes:** — (none)
**Related:** `0004-m2-workspace-tools.md`, `0005-m3-mcp-integration.md`, `docs/roadmap.md` §6, `docs/security.md` §3

## Question

How do we flesh out the `elevated` and `full_access` agent tiers that
M1 left as empty stubs, while honouring the standing constraint
"never grant an agent unrestricted network / fs / system access
without a human-in-the-loop backstop"?

## Findings

### The two threats M4 has to defend against

1. **Privilege escalation via prompt injection.** A restricted-tier
   agent is jailbroken by a malicious README / web page / PR
   description into instructing the user to run `--tier full_access`.
   The user, not understanding the difference, runs it. The
   unrestricted tier then does whatever the attacker wanted.

2. **Accidental data egress.** A well-meaning user runs `full_access`
   for "just to install this one npm dep", the model-written code
   has a typo, and the typo exfiltrates the home directory to a
   remote host. There is no second chance to abort.

The defence for both is the same: **the full_access tier must not
run without a deliberate, time-bounded human confirmation, and every
run must leave a paper trail.**

### Confirmation prompt: timeout-as-deny semantics

Three options considered:

- **a. Hard `y/N` (no timeout).** Every full_access run requires an
  explicit `y`. Inconvenient for long-running scripted runs but
  safest.
- **b. Configurable timeout (chosen).** 30 s default; the user can
  raise it via `SMOLCODE_FULL_ACCESS_CONFIRM_TIMEOUT_S` or
  `--confirm-timeout`. Timeout-as-deny: if no answer in 30 s, the
  run is cancelled (exit code 4). Setting the timeout to 0 means
  "require `y` even on instant-decline" (most paranoid).
- **c. Always-on (no prompt).** Rejected. The user already
  acknowledged in M4 planning that this defeats the human-in-the-
  loop backstop.

User's M4 decision (recorded 2026-08-19): **option b** with 30 s
default and editable via env var / flag.

### Audit log: append-only JSONL

Why append-only?

- Tamper-evident at the file-handle level: the `AuditSink`
  constructor refuses any mode other than `a` or `a+`. A bug or
  attacker who tries `mode="w"` gets `AuditError`, not silent
  truncation.
- Per `docs/security.md` §8 the audit log is the only record of
  who ran what when. A truncated log is worse than no log.
- Per-line JSON keeps the log greppable and streamable.

Event vocabulary: `start`, `step`, `error`, `end`. New events are
added by extending `AuditSink.record()` (no new method needed).

### Network allowlist: data structure only

The roadmap §6 (M4) explicitly defers iptables enforcement inside
the container to v1.1. M4 ships the data structure (`Tier.network_allowlist`)
so M4.x can wire iptables without an API break.

Semantics (documented in `config.py`):

- `()` → no hosts (paired with `network="none"`)
- tuple of hostnames → allowed egress (paired with `network="restricted"`)
- `("*",)` → sentinel meaning "all hosts" (paired with `network="open"`)

v1 containers still run with `network_mode="none"` for restricted
and elevated (the Docker executor's bind-mount + no-network is the
backstop until iptables lands). full_access containers do not get
`network_mode="none"` — they get the default bridge, by design.

## Decisions

| ID | Decision |
|---|---|
| D1 | Confirmation prompt: 30 s hard `y/N`; editable via `SMOLCODE_FULL_ACCESS_CONFIRM_TIMEOUT_S` (env) and `--confirm-timeout` (flag). Timeout-as-deny. Setting to 0 means "require `y` even on instant-decline". (User's M4 decision.) |
| D2 | `prompt_confirmation` accepts `y` or `yes` (case-insensitive, after strip). Anything else (empty, `n`, `no`, garbage) is deny. |
| D3 | The prompt fires BEFORE the agent is built, in `cli.py:main()`. A denial never spends model tokens. |
| D4 | `AuditSink` is append-only: refuses any mode other than `a` / `a+`. Test `tests/test_audit.py::TestModeEnforcement` covers the rejection. |
| D5 | Audit log path: `--audit-log` flag → `SMOLCODE_AUDIT_LOG` env var → `<cwd>/logs/audit.jsonl` (default). Parent dirs are created. |
| D6 | `--no-audit` flag skips the audit sink entirely (not recommended for `full_access`). |
| D7 | The `elevated` tier ships with extra imports (`os`, `sys`, `tempfile`, `hashlib`, `shutil`, `glob`, `collections`, `itertools`, `functools`) and extra commands (`pip`, `npm`, `node`, `curl`, `jq`, `make`). NO ssh / docker / kubectl / aws / gcloud / az — those stay exclusive to `full_access`. |
| D8 | The `full_access` tier ships with the widest import set, the widest command set (incl. ssh / scp / rsync / docker / kubectl / terraform / ansible / aws / gcloud / az CLIs), and `network="open"` with `network_allowlist=("*",)`. |
| D9 | Network allowlist enforcement (iptables / `--cap-add=NET_ADMIN` + script) is **deferred to v1.1** per roadmap §6. The data structure is exposed now so M4.x can wire it without an API break. |
| D10 | `Tier.network_allowlist` is part of the dataclass equality / hash, so a tier with `network_allowlist=("github.com",)` does not equal one with `network_allowlist=()`. This prevents accidental tier substitution. |
| D11 | Exit codes: 0 = success, 1 = error, 2 = config error, 3 = missing API key, 4 = confirmation denied / timeout, 5 = audit sink init failure, 130 = Ctrl-C. (130 is the standard POSIX SIGINT code.) |
| D12 | `cli.py` factories: `build_restricted_agent`, `build_elevated_agent`, `build_full_access_agent` (delegates to `make_agent`). Tier dispatch is a dict lookup; no `if/elif` chain. |

## Files added / changed

| Path | Purpose |
|---|---|
| `smolcode/src/smolcode/audit.py` | `AuditSink` + `AuditError` + `default_audit_path` |
| `smolcode/src/smolcode/confirm.py` | `prompt_confirmation`, `confirm_full_access`, `resolve_timeout_s`, `ConfirmationDenied` |
| `smolcode/src/smolcode/agents/elevated.py` | `build_elevated_agent` |
| `smolcode/src/smolcode/agents/full_access.py` | `build_full_access_agent` |
| `smolcode/src/smolcode/agents/__init__.py` | export the two new factories |
| `smolcode/src/smolcode/config.py` | added `network_allowlist` field to `Tier`; fleshed out `_default_tiers()` |
| `smolcode/src/smolcode/cli.py` | per-tier dispatch, confirmation prompt, audit sink, new flags |
| `smolcode/src/smolcode/docker/elevated.Dockerfile` | adds git/curl/jq/make |
| `smolcode/src/smolcode/docker/full_access.Dockerfile` | adds ssh/rsync/docker/kubectl/terraform/ansible/aws/gcloud/az |
| `smolcode/src/smolcode/tests/test_audit.py` | 19 tests (mode enforcement, append-only, JSONL, lifecycle, env override, thread safety) |
| `smolcode/src/smolcode/tests/test_confirm.py` | 15 tests (resolve_timeout_s, prompt_confirmation, confirm_full_access) |
| `smolcode/src/smolcode/tests/test_tiers.py` | 12 tests (Tier shape, agent factory exports) |
| `smolcode/src/smolcode/tests/test_cli.py` | expanded from 4 → 14 tests (tier dispatch, confirmation, audit) |

## Rejected alternatives

- **`always-yes` flag** to skip the prompt. Rejected — the prompt
  is the human-in-the-loop backstop; an opt-out flag undermines
  `docs/security.md` §10's threat model.
- **`sudo-style` password prompt.** Rejected — there's no password
  to enter; the user is the operator.
- **Per-tool confirmation (every ssh command).** Rejected — too
  noisy; the per-run prompt catches the common case ("am I about
  to give this agent the keys?") and the audit log captures the
  granular details.
- **Audit log to syslog / journald.** Rejected for v1 — adds a
  platform dependency. The local JSONL is greppable, rotatable
  with `logrotate`, and inspectable with `jq`.

## Acceptance gates (per roadmap §6 M4)

| Gate | Status |
|---|---|
| `make quality` (ruff check + format) green | PASS |
| `make test` green | PASS (198 tests: 139 prior + 59 new for M4) |
| `smolcode --print-config` shows all three tiers with network_allowlist | PASS |
| `smolcode --smoke --tier elevated "echo hi"` runs without prompt | PASS |
| `smolcode --smoke --tier full_access "echo hi"` with `--confirm-timeout 1` and no stdin → exit 4 (denied) | PASS |
| `smolcode --smoke --tier full_access "echo hi"` with piped `y` → exit 0 (run proceeds) | PASS |
| `AuditSink(mode="w")` raises `AuditError` | PASS |
| Audit log writes `start` + `end` events to default `<cwd>/logs/audit.jsonl` | PASS |
| Audit log appends; does not truncate prior content | PASS |
| Elevated + full_access Dockerfiles documented (built lazily by executor) | PASS (Dockerfiles present) |
| `docs/security.md` §3.2 + §3.3 cross-referenced from CLI | PARTIAL (cross-reference added; security.md update deferred to M7 polish) |

## Open questions deferred to M4.x / v1.1

1. **iptables enforcement for `elevated` network_allowlist** (D9).
2. **Audit log rotation policy** — currently we just append. A
   sample `logrotate.conf` snippet ships at M7.
3. **Audit log redaction filter** — currently we log the raw task
   description. If a task description contains a secret (e.g. an
   accidental `Bearer ...` paste), the secret lands in the audit
   log. The `RedactSecretsFilter` ships at M4.x.
4. **Per-tool confirmation for destructive operations within
   full_access** (e.g. `git push --force`). Rejected for M4
   because the per-run prompt catches the common case; revisit if
   user feedback indicates the model is too noisy inside an
   already-confirmed run.

## Self-review sign-off

Per M7 (the user chose self-review), this decision document is the
artifact. The implementer is the reviewer.

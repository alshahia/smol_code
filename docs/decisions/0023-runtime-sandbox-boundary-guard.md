# 0023 — Runtime sandbox-boundary guard + hang-aware cleanup (bugfix)

**Date:** 2026-08-23
**Status:** SHIPPED — v1.7.1
**Type:** Bugfix (defense-in-depth on top of decisions 0021 + 0022)
**Effort:** ~0.75 person-day, ~250 LOC Python + ~340 LOC tests

---

## 1. Context and motivation

Decisions 0021 and 0022 fixed two failures from the user's
"create a simple todo app" Web UI session:

* 0021 added a tier-aware sandbox-boundary note to every
  sandbox-tier `CodeAgent`'s system prompt, telling the LLM that
  `smolcode` is host-only.
* 0022 added `agent.cleanup()` to `run_in_thread`'s `finally`
  block so the Docker container is removed on every exit path.

Both shipped, both tested (878 passed + 3 skipped at the time).
On the very next user attempt, the Web UI failed again — in the
**same way** as before:

```
ModuleNotFoundError: No module named 'smolcode'
Cell In[2], line 70
    70 import smolcode
```

and then on the retry, **the same** `Bind for 127.0.0.1:8888
failed: port is already allocated` — because a new zombie container
(`jovial_taussig`) was holding the port from the just-failed run.

So decision 0021's prompt-only fix was not actually preventing the
LLM from writing `import smolcode`, and decision 0022's `finally`
cleanup was not actually running on the hang path (the runner
thread was still blocked inside the Jupyter kernel when the user
closed the Web UI; the `finally` never got a chance to fire).

This decision closes both gaps with **defense-in-depth**.

### 1.1 Why the prompt-only fix failed

The instruction is correctly injected into the system prompt. We
verified this end-to-end: `agent.instructions` is 981 chars, present
in the rendered system prompt at the `{{custom_instructions}}` slot,
and the rendered prompt contains the exact text `"NEVER write
`import smolcode`"`. The MiniMax-M3 model still wrote `import smolcode`
on its second step.

Two contributing factors:

1. **Long context, low priority.** The smolagents default system
   prompt is ~10 KB; our note is appended at the very end. The
   model "attends" to the early sections (tool list, ReAct rules)
   more than the tail.
2. **Confusion between framework names.** The model is told
   `smolagents` is available (it is — the sandbox image includes
   `smolagents + jupyter_client + ipykernel`); it then
   mis-generalizes that `smolcode` (the orchestrator that wraps
   `smolagents`) must also be available.

Prompt-only fixes don't survive model confusion. We need a runtime
guard.

### 1.2 Why the finally-only cleanup failed

`agent.run(task)` is a blocking call that synchronously sends each
code action to the Jupyter kernel via `requests.post(...)`. When
the kernel is hung (because pip is downloading), the call never
returns. The runner thread is alive but blocked. The `finally`
block only fires when the call returns — which may be never.

If the Web UI's SSE connection drops, the runner thread is
**not** notified. It keeps blocking on the kernel forever,
holding the container alive.

We need a wall-clock deadline that fires regardless of kernel
state.

---

## 2. Goals

1. **G1** — Prevent the LLM from successfully executing
   `import smolcode` or `!pip install smolcode` inside any sandbox
   tier, regardless of what the system prompt says. The error must
   be **actionable** (tell the model what to do instead) so the
   next reasoning turn recovers without further prompting.
2. **G2** — Bound the lifetime of `agent.run()` in
   `run_in_thread` so a hung Jupyter kernel can never hold
   `127.0.0.1:8888` past a configurable deadline. On timeout, the
   Docker container is killed and the run is published as
   `stopped` with a clear wall-clock-timeout message.
3. **G3** — Layer cleanly on top of decisions 0021 (prompt note)
   and 0022 (finally cleanup). No regressions in either. The guard
   must be executor-agnostic (works for Docker, Modal, E2B, future
   remote executors).
4. **G4** — Be **invisible** in the happy path: no extra latency,
   no log noise, no behavioral change for code that does NOT
   violate the boundary.

---

## 3. Non-goals

1. **NG1** — Stop the LLM from writing the bad code in the first
   place. That's a model-alignment problem; out of scope for a
   tool-side fix. We catch the bad code at the executor boundary
   instead.
2. **NG2** — Authorize any host-only module. `smolcode` is never
   importable inside a sandbox. If a future tier genuinely needs
   `smolcode.config`, expose it as a **Tool**, not a module.
3. **NG3** — Patch smolagents upstream. The proxy pattern is local
   to `smolcode` and works against any `PythonExecutor` shape.
4. **NG4** — Add a per-step timeout (e.g. "no model call should
   take more than 60s"). Wall-clock on the whole run is good
   enough for v1.7.1; per-step is a v1.8 candidate.
5. **NG5** — Replace the system-prompt note from 0021. The
   instruction is still useful — it stops the well-behaved models
   cold and saves a step. 0023 is the safety net for the
   not-so-well-behaved ones.

---

## 4. Design

### 4.1 Layer A — `GuardedExecutor` proxy

```
CodeAgent
  └─ python_executor: GuardedExecutor   (NEW in 0023)
        ├─ _inner: DockerExecutor       (smolagents)
        └─ _tier: "restricted" | "elevated" | "full_access"
```

`make_agent()` (in `agents/base.py`) builds the `CodeAgent`
unchanged, then swaps `agent.python_executor` for a
`GuardedExecutor` around the original. The proxy:

* **Delegates** every attribute access (`send_tools`,
  `send_variables`, `cleanup`, anything future smolagents adds)
  via `__getattr__` to the inner executor. No behavioral change
  for those methods.
* **Pre-checks** every code action on `__call__` via
  `check_sandbox_boundary(code, tier)`.
  - Returns the inner executor's `CodeOutput` unchanged if the
    code is safe.
  - Raises `SandboxBoundaryViolation` (a `RuntimeError` subclass)
    if the code attempts to import or pip-install a host-only
    module.

`smolagents` catches the exception in `CodeAgent._step_stream`
(`agents.py:1734`) via the broad `except Exception` around
`self.python_executor(...)`, sets `error_msg = str(e)`, and raises
`AgentExecutionError(error_msg, self.logger)`. The model sees the
message as an observation in its next reasoning turn and recovers
without further prompting.

#### What gets detected

| Pattern | Detector | Example |
|---|---|---|
| `import smolcode` | `ast.Import` walk | `import smolcode`, `import smolcode as sc`, `import json, smolcode, os` |
| `from smolcode …` | `ast.ImportFrom` walk (level == 0) | `from smolcode import agents`, `from smolcode.agents.base import make_agent` |
| `!pip install … smolcode …` | regex on shell-magic lines | `!pip install smolcode`, `!pip install -q pillow smolcode numpy` |
| `!pip3 install … smolcode …` | regex | `!pip3 install smolcode` |
| `%pip install … smolcode …` | regex | `%pip install smolcode` |
| `!python -m pip install … smolcode …` | regex | `!python -m pip install smolcode` |
| `!python3 -m pip install --quiet smolcode` | regex | (any combo of pip / pip3 / python -m pip + flags + smolcode) |

#### What does NOT get detected (deliberate)

| Pattern | Why not flagged |
|---|---|
| `import smolagents` | `smolagents` IS installed in the sandbox image; flagging would be wrong |
| `from .sibling import X` | relative imports are always sandbox-safe |
| Comments containing the strings | AST walk ignores comments |
| String literals mentioning `smolcode` | AST walk ignores strings |
| Docstrings | same |
| Code that fails `ast.parse` (SyntaxError) | we return None; the executor surfaces the real SyntaxError with proper line context |

The detector tolerates a Jupyter cell that mixes Python and
shell-magic lines (e.g. `import smolcode\n!pip install numpy`):
the shell-magic lines are blanked out before `ast.parse` so the
import is still detected.

#### Tier gating

`check_sandbox_boundary` returns `None` immediately for any tier
whose name is NOT in `SANDBOX_TIERS = {"restricted", "elevated",
"full_access"}`. The orchestrator tier (which runs on the host
with `executor_type="local"`) is excluded; `smolcode` IS
available on the host, so the guard would be misleading. The
exclusion happens at the gate, not the detector, so the detector
itself has a single code path.

### 4.2 Layer B — wall-clock timeout in `run_in_thread`

```
run_in_thread(run, settings):
  ...
  pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=...)
  run_future = None
  try:
    agent = _build_agent_for_run(run, settings)        # may raise
    ...                                                 # step callbacks
    run_future = pool.submit(agent.run, run.task)       # blocks until done or hung
    try:
        answer = run_future.result(timeout=_MAX_RUN_WALL_S)
        run.result = _safe_str(answer)
    except concurrent.futures.TimeoutError:
        # mark run as stopped, clear error message
        final_status = STATUS_STOPPED
        run.error  = "wall-clock timeout: ..."
        exit_code   = 124                              # standard timeout code
        # do NOT call cleanup() here -- the existing finally will
    except _StopRequested:
        ...
    except KeyboardInterrupt:
        ...
    except Exception as e:
        ...
  finally:
    if agent is not None:
        try: agent.cleanup()          # ALWAYS tears down the container
        except Exception: _log.warning(...)
    try: pool.shutdown(wait=False)     # release the worker; do NOT block on it
    except Exception: pass
```

Key choices:

- **Why `concurrent.futures.ThreadPoolExecutor`?** It is part of
  the stdlib since Python 3.2 and gives us:
  - `future.result(timeout=…)` to bound the wait
  - `pool.shutdown(wait=False)` to release the runner thread
    immediately after the finally block
  - Per-run thread naming (`smolcode-<run_id>`) so debug logs are
    traceable
- **Why `wait=False` on shutdown?** The hung `agent.run` is
  blocked on a network request to a Docker container we are about
  to kill. The in-flight request fails as soon as the container
  is gone; the worker thread exits on its own within seconds. We
  do not block the runner thread on that.
- **Why not call `agent.cleanup()` from the timeout handler?**
  The `finally` block handles it. Calling it twice is wasteful
  (even though idempotent), and keeping it in `finally` means
  there is exactly one place to look for the cleanup invariant.

### 4.3 Configuration

| Env var | Default | Purpose |
|---|---|---|
| `SMOLCODE_WEB_RUN_TIMEOUT_S` | 900 | Wall-clock deadline for a single Web UI run. After this, `agent.cleanup()` is called in the `finally` and the run is published as `stopped`. 15 minutes is generous for the typical coding task; raise it for `full_access` runs that legitimately need long iptables / terraform / kubectl sessions. |
| `SMOLCODE_WEB_RUN_DRAIN_S` | 30 | Reserved for future use; currently a no-op (we rely on the kernel request failing naturally after `agent.cleanup()`). |

Both are documented in `agent_runner.py` as module-level constants
and overridable via env var. Tests override `_MAX_RUN_WALL_S`
directly via `monkeypatch`.

### 4.4 What the user sees

**Before 0023** (model writes `import smolcode`):

```
ERROR: Could not find a version that satisfies the requirement smolcode (from versions: none)
ERROR: No matching distribution found for smolcode

ModuleNotFoundError: No module named 'smolcode'
Cell In[2], line 70
  70 import smolcode
Code execution failed: ...
```

→ model retries, hits the same error, retries again, eventually
gives up or hangs. Web UI shows raw traceback with no hint.

**After 0023** (model writes `import smolcode`):

```
SandboxBoundaryViolation: refused to execute code that violates the sandbox boundary.
Detected: import of host-only module `smolcode`.

`smolcode` is the HOST-side orchestrator and is NOT installed inside this Docker container.
It cannot be imported or pip-installed here. If you need to interact with host-side state
(audit log, config dump, redact-filter preview, etc.), that capability MUST be exposed as a
TOOL -- not reached via `import smolcode` or `!pip install smolcode`.

Re-emit your code WITHOUT the host-only import / install. Use the workspace tools listed in
your system prompt (write_file, read_file, run, etc.) for all host interaction.
```

→ model retries without the bad import, succeeds. Wall-clock
time saved: ~10s × N retries.

**After 0023** (kernel hangs, regardless of cause):

→ After `SMOLCODE_WEB_RUN_TIMEOUT_S` (default 900s), the runner
returns. `agent.cleanup()` runs in `finally`, container is killed,
port 8888 is freed. Web UI shows:

```
status: stopped
error: wall-clock timeout: run exceeded 900s without completing; executor was forcibly stopped
```

→ Next run binds port 8888 immediately.

---

## 5. Validation

### 5.1 Test plan

`sandbox_guard.py` (NEW, 65 tests):

| Group | Tests |
|---|---|
| Tier gating | orchestrator returns `None`, all 3 sandbox tiers return a message, `TypeError` on non-Tier |
| Python import AST | flags `import smolcode`, `from smolcode …`, mixed-import lines, nested imports, `import X as Y` |
| Python import AST (negative) | does NOT flag `import smolagents`, `from smolagents …`, `import json`, relative imports, strings/comments/docstrings mentioning smolcode |
| Python import AST (edge) | tolerates `SyntaxError` (returns None, executor surfaces the real error), tolerates empty code, detects `import smolcode` even when the cell ALSO contains `!ls` or `%pwd` (shell-magic stripping) |
| pip-install regex | flags `!pip install smolcode`, `!pip3`, `%pip`, `!python -m pip`, `!python3 -m pip`, `%python -m pip`, with arbitrary flag combos and other packages |
| pip-install regex (negative) | does NOT flag `!pip install numpy`, `!pip install pillow`, `!pip install smolagents` |
| Error message shape | message mentions HOST-side orchestrator, NOT installed, Re-emit, workspace tools |
| `GuardedExecutor` proxy | raises `SandboxBoundaryViolation` for bad code; delegates good code; delegates `send_tools`, `send_variables`, `cleanup`, arbitrary attributes; raises `AttributeError` for non-inner attrs; `MagicMock` inner is callable as `__call__` |
| `SandboxBoundaryViolation` | subclasses `RuntimeError` (smolagents catches it), is catchable as `Exception` |
| End-to-end via `make_agent` | restricted-tier agent's `python_executor` IS a `GuardedExecutor`; `import smolcode` raises at `__call__` time |
| Regex coverage | every pip-magic pattern compiles and matches its example |

`test_agent_runner.py` (3 new tests in `TestRunInThreadWallClockTimeout`):

| Test | Asserts |
|---|---|
| `test_run_returns_when_agent_hangs_forever` | mock `agent.run` that sleeps 60s; `run_in_thread` returns within ~3s (timeout is monkeypatched to 0.3s); `agent.cleanup` called once; `run.status == STATUS_STOPPED`; `run.error` mentions wall-clock timeout |
| `test_run_status_is_done_when_agent_completes_within_timeout` | happy path under the new wrapper still works; run is DONE, cleanup called once |
| `test_pool_is_shut_down_after_timeout` | bounded runtime after timeout proves `pool.shutdown(wait=False)` released the worker |

### 5.2 Pre-existing tests still pass

* `test_agent_runner.py::TestRunInThreadDockerCleanup` — all 6
  decision-0022 tests still pass; the new `finally` body is a
  strict superset of the old one.
* `test_agent_prompting.py` — all 19 decision-0021 tests still
  pass; the prompt note is unchanged.
* `test_agents_base.py` — all 6 tests still pass; the new
  `wrap_executor` call is additive.

### 5.3 Numbers

| Run | Result |
|---|---|
| `ruff check src` | All checks passed |
| `ruff format --check src` | All 87 files already formatted |
| Targeted pytest (10 critical files) | **245 passed + 3 skipped in 64.78s** |
| Full pytest (rest of suite) | **706 passed in 71.92s** |
| **Combined** | **946 passed + 3 skipped** |

Test count progression: M16 (853) → 0021 (872) → 0022 (878) →
**0023 (946)**; +68 tests (19 from 0021's prompting tests were
already counted; 0023 adds 65 sandbox_guard + 3 wall-clock
timeout = +68 net).

---

## 6. Risks and rollback

### 6.1 Risks

* **R1 — False positive in `check_sandbox_boundary`.** A model
  that legitimately writes code that looks like
  `import smolcode` (e.g. tests for a Python project that happens
  to be named `smolcode`) will be blocked. Mitigated by: the
  guard only fires for SANDBOX tiers; the orchestrator and CLI
  can run code anywhere; the error message tells the model
  exactly what to do. If a user hits this in production they can
  add the module to `_HOST_ONLY_MODULES` allowlist.

* **R2 — Wall-clock timeout too aggressive.** 15 minutes may be
  too short for a `full_access` terraform-apply. Mitigated by:
  `SMOLCODE_WEB_RUN_TIMEOUT_S` env var; documented in
  `agent_runner.py`. If a run legitimately needs more, the user
  bumps the env var.

* **R3 — Wall-clock timeout too lax.** 15 minutes per run means
  a single misconfigured task can hold the GPU-quota'd provider
  key for 15 minutes. The audit log still records the run, so
  this is observable. We can revisit with per-step timeouts in
  v1.8 (NG4).

* **R4 — `pool.shutdown(wait=False)` leaks worker threads.** A
  hung Jupyter request may keep the worker thread alive for
  several seconds after `run_in_thread` returns. In production,
  the request fails as soon as the container is killed
  (typically < 5s). In tests, the mock `_hang_forever` sleeps for
  60s; the thread is harmless (just sleeping) and dies on its
  own. Acceptable for v1.7.1.

### 6.2 Rollback

Both layers can be reverted independently:

- **Layer A:** delete the `wrap_executor(...)` line from
  `agents/base.py:make_agent`. The guard module can stay in
  place; it just isn't wired in. Decision 0021's prompt note
  becomes the sole defense again (which we already know is
  insufficient).
- **Layer B:** delete the `pool = ThreadPoolExecutor(...)`,
  `run_future = pool.submit(...)`, `run_future.result(timeout=...)`,
  and `pool.shutdown(wait=False)` lines. Restore the bare
  `answer = agent.run(run.task)` call. Decision 0022's `finally`
  cleanup is back to being the only defense against the hang.

No data is lost on rollback; the audit log is unchanged.

---

## 7. Files

| File | Action | LOC |
|---|---|---|
| `smolcode/src/smolcode/sandbox_guard.py` | NEW | ~270 |
| `smolcode/src/smolcode/agents/base.py` | edit (wrap executor + import) | +6 |
| `smolcode/src/smolcode/web/agent_runner.py` | edit (Future timeout + pool shutdown) | +35 |
| `smolcode/src/smolcode/tests/test_sandbox_guard.py` | NEW | ~390 |
| `smolcode/src/smolcode/tests/test_agent_runner.py` | edit (TestRunInThreadWallClockTimeout) | +120 |
| `smolcode/README.md` | edit (add 0023 note + update status banner) | +30 |
| `docs/decisions/0023-runtime-sandbox-boundary-guard.md` | NEW (this doc) | ~370 |

---

## 8. Decision

Ship both layers together. The prompt-only fix (0021) is
necessary but not sufficient; the `finally`-only cleanup (0022) is
necessary but not sufficient; together with 0023 they form the
minimum viable defense for the Web UI's "create a todo app" task
and the broader class of failures where the LLM ignores sandbox
guidance and/or hangs the kernel.

Acceptance criteria:

1. ✅ `import smolcode` raises `SandboxBoundaryViolation` BEFORE
   the kernel sees it (verified at runtime; 8 unit tests pin it).
2. ✅ `!pip install smolcode` raises `SandboxBoundaryViolation`
   (verified at runtime; 9 unit tests pin it).
3. ✅ `agent.cleanup()` runs within `_MAX_RUN_WALL_S + 1s` of a
   hang (3 new tests pin it; existing 0022 tests still pass).
4. ✅ No regressions: 946 passed + 3 skipped; ruff clean; format
   clean.

---

## 9. Closeout

* **Shipped:** 2026-08-23 (same day as 0021 + 0022; triple bugfix
  release v1.7.1)
* **Re-test in 30 days:** if the wall-clock timeout fires
  spuriously in production, bump the default or expose a
  per-tier override.
* **v1.8 candidate:** per-step timeout (NG4); consider promoting
  the `_HOST_ONLY_MODULES` set to a tier-aware config so each
  tier can declare its own allowlist / denylist (currently the
  list is global).
* **Smolagents upstream PR opportunity:** the guard would be a
  useful general-purpose feature (`additional_denied_imports`
  arg on `CodeAgent`). Worth proposing after v1.7.1 has soaked
  for a release cycle.

---

## 10. Followup: Layer B (v1.7.1.2) — sanitise `send_tools` infrastructure code

**Date:** 2026-08-23 (same day; back-to-back bugfix)
**Status:** SHIPPED — v1.7.1.2
**Type:** Bugfix on top of decision 0023 Layer A
**Effort:** ~0.25 person-day, +22 layer-B unit tests; total 968 passed + 3 skipped

### 10.1 The bug Layer A missed

After shipping 0023 Layer A, the user re-ran the same "create a simple
todo app" task in the Web UI and **still** hit `ModuleNotFoundError:
smolcode` in the Jupyter kernel — followed by `RecursionError: maximum
recursion depth exceeded`.

Root cause: smolagents registers tools by calling `executor.send_tools({...})`
**before** the first model step. Inside that call (smolagents/remote_executors.py:108-113),
it calls `self.install_packages(requirements)` and `self.run_code_raise_errors(static_tools_code)`
**directly** on the inner executor. These bypass our `__call__` proxy
entirely, so Layer A never sees them.

Where does `import smolcode` come from in tool-def code? `Tool.to_dict()`
in `smolagents/tools.py` auto-extracts imports via `get_imports(source_code)`
and unions them with `{"smolagents"}`. Our tools (`write_file`,
`patch_file`, `run`, `git_push`) all start with `from smolcode.session
import ...`, so `requirements` ends up containing `"smolcode"` — and
`instance_to_source(...)` produces tool-definition code whose first
line is `import smolcode`. Both reach the Jupyter kernel.

### 10.2 The Layer B design

Two additional methods on `GuardedExecutor` mirror Layer A but target
the infrastructure paths:

* `GuardedExecutor.install_packages(additional_imports)` filters
  `smolcode` (and any other host-only package) out of the list before
  delegating. Empty-filtered result → returns `[]` (no inner call).
* `GuardedExecutor.run_code_raise_errors(code)` strips host-only
  lines from the tool-def code (same logic as Layer A's
  `check_sandbox_boundary`, but applied as a sanitizer rather than
  a rejecter). Empty-after-strip → returns a benign `CodeOutput`
  (`output=None, logs="", is_final_answer=False`) so smolagents
  doesn't see `ModuleNotFoundError` from an empty cell.

Both originals are captured by `object.__setattr__` at `__init__`
time and reused by Layer B calls. They remain valid even while
`inner.install_packages` is temporarily rebound (see 10.3).

### 10.3 Why `__getattr__` and the lambdas had to be reworked

Layer B needs to be reached by smolagents' `send_tools` flow even
though smolagents calls `install_packages` / `run_code_raise_errors`
on `inner` (not `proxy`). The naive first take was:

```python
inner.install_packages = lambda pkgs: self.install_packages(pkgs)
inner.run_code_raise_errors = lambda code: self.run_code_raise_errors(code)
```

but that recurses **infinitely**: the lambda calls proxy's method,
which calls `self._inner.install_packages(filtered)` — which is the
lambda again. `RecursionError`.

**Invariant 0023-D** — `__getattr__` is plain delegation; do NOT
rebind bound methods to the proxy (breaks `__slots__`-protected
attribute assignments inside smolagents' `send_tools` such as
`self.static_tools = {...}`).

**Invariant 0023-E** — `wrap_executor` must work for both Remote
executors (which have `run_code_raise_errors` + `install_packages`)
AND Local executors (which have neither). The `_SENTINEL` pattern in
`send_tools` makes layer B a clean no-op for `LocalPythonExecutor`.

### 10.4 Final wiring

Plain `__getattr__`; originals captured at construction; routing
lambdas capture the originals as default-arg closure variables so
they call `_real(filtered_pkgs)` directly — never `inner.<name>(...)`.

### 10.5 Tests added (+22; total 968 + 3 skipped)

* `test_strip_host_only_lines_*` (12) — strips, mixed cells, line
  preservation, empty input, only-bad-lines.
* `test_run_code_raise_errors_*` (5) — strips, pass-through,
  empty-all-lines returns benign CodeOutput, pass-through of inner
  exception, noop for orchestrator.
* `test_install_packages_*` (4) — filters, empty-after-filter,
  pass-through safe, noop for orchestrator.
* `test_guarded_executor_blocks_send_tools_bypass_path` — REGRESSION
  for the actual user bug: simulates smolagents' `send_tools` flow
  exactly as `remote_executors.py:108-113` does.

### 10.6 Closure

After this followup, the Web UI launched cleanly with `MiniMax-M3` on
the same "create a simple todo app" task — no more `ModuleNotFoundError:
smolcode`, no more `RecursionError`.

The 409 Conflict on container cleanup observed in the same CLI run
is the pre-existing benign race between `auto_remove=True` and our
`cleanup()` (0022 documented it) — separate from 0023 Layer A/B and
out of scope here.

Re-test in 30 days, v1.8 candidates, and upstream PR opportunity are
unchanged from §9.

## 11. Followup: decision 0024

After 0023 landed, the Web UI's `POST /api/runs` returned `status=error`
with `OSError: [Errno 22] Invalid argument` in 4.4 s with no usable
stack. The broad `except Exception` block in `agent_runner.run_in_thread`
only stored `type(e).__name__ + ": " + str(e)` — the exact gap this
document's followup plan called out. Capturing the full traceback
revealed the real bug was `UnicodeEncodeError: 'charmap' codec can't
encode...` raised by smolagents' `StepLogger.log -> Rich console.print
-> legacy_windows_render` path on Windows when encoding pip's
emoji/box-drawing output through the `cp1252/cp1256` codec.

Decision `0024-web-ui-traceback-and-utf8.md` ships three connected
fixes:

1. **Traceback capture** in `agent_runner.run_in_thread`'s broad
   except — appends `traceback.format_exc()` to `run.error` (capped at
   8 KB) AND surfaces it in `EVT_ERROR.traceback`.
2. **Defensive wrappers** for the three `step_callbacks.register(...)`
   calls (ActionStep, PlanningStep, FinalAnswerStep) + `pool.submit(...)`
   so transient failures log + continue instead of aborting.
3. **UTF-8 stdio via `_unicode_env.py::setup_unicode_env()`**, called
   from `smolcode/__init__.py` at package import time, BEFORE any
   submodule imports smolagents — so by the time smolagents
   constructs its Rich Console, `sys.stdout.encoding` is already UTF-8.

Live end-to-end validated on `deepseek-v4-flash`: Web UI run of
"create a simple todo app" now completes in 114.28 s with
`status=done` and produces `todo_app/todo.py`. Combined test count:
979 + 3 (was 968 + 3 after 0023).

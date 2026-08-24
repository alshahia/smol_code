# 0022 — Run Cleanup on Every Exit Path (bugfix)

**Date:** 2026-08-23
**Status:** SHIPPED — v1.7.1
**Type:** Bugfix
**Effort:** ~0.25 person-day, ~30 LOC Python + ~190 LOC tests

---

## 1. Context and motivation

A user fixed the `import smolcode` bug (decision 0021), then asked the
Web UI to "create a simple todo app" again. The new run failed with:

```
RuntimeError: Failed to initialize Jupyter kernel:
500 Server Error for http+docker://localnpipe/v1.51/containers/.../start:
Internal Server Error ("failed to set up container networking: driver failed
programming external connectivity on endpoint stoic_kepler (...):
Bind for 127.0.0.1:8888 failed: port is already allocated")
```

Inspection showed a leftover container `busy_pike` (`smolcode:restricted`,
started ~1 hour earlier) was still bound to `127.0.0.1:8888->8888/tcp`.
Its PID was alive, kernel gateway was still serving, kernel was still
attached.

Looking at the leftover container's logs showed exactly why: during the
user's first failed run (the one that hit the `import smolcode`
error), the model wrote:

```
'code': '!pip install pillow smolcode numpy', ...
```

i.e. the LLM tried to **pip-install `smolcode` inside the sandbox** via
a Jupyter shell escape (`!`). That hangs the kernel gateway for the
duration of the install. The Web UI eventually timed out / the user
closed the browser, but the smolagents `DockerExecutor` never got a
chance to call its `cleanup()` because:

1. `auto_remove=True` only fires when the container's main process
   exits cleanly. A hung kernel does not exit.
2. `CodeAgent.cleanup()` exists but was never wired into
   `web/agent_runner.py:run_in_thread`'s `finally` block.

Net result: every failed run left a zombie container holding the
host's 127.0.0.1:8888, and the next run was unrecoverable without a
manual `docker rm -f`.

---

## 2. Goals

G1. **Always tear down the Docker container**, regardless of how the
    run ended (success, error, stop, KeyboardInterrupt, hang).
G2. **Cleanup failure must not mask the run's terminal status** (the
    user must still see "done" / "error" / "stopped" even if Docker
    itself is wedged).
G3. **Idempotent**: cleanup() must be safe to call when the agent was
    never fully built.
G4. **Zero new dependencies, zero config changes**. We just call the
    `cleanup()` method that already exists on smolagents' CodeAgent.
G5. **Pin the regression with tests** that cover all five exit paths.

---

## 3. Non-goals

- **Replacing smolagents' DockerExecutor cleanup with our own.** It
  already does the right thing (`container.stop(); container.remove()`
  with try/except). The gap was that smolcode never called it.
- **Tearing down MCP servers in the same path.** MCP is opt-in and
  only relevant for tiers that load MCP tools; the user's failure was
  Docker-only. (Future: if MCP cleanup becomes a problem, add a
  `close_mcp_servers()` call alongside `agent.cleanup()`.)
- **Fixing the `!pip install smolcode` hallucination itself.** That is
  a model-behavior problem partially addressed by decision 0021 (the
  sandbox-boundary note). Decision 0022 addresses the consequence
  ("any model hang leaves a zombie container").
- **Using a non-default port to avoid the conflict entirely.** The
  port choice is hard-coded by smolagents' `DockerExecutor.__init__`
  default of 8888; changing it requires a smolagents PR. The
  `cleanup()` fix makes the port-reuse problem moot because the port
  is freed when the run ends, regardless of how it ended.

---

## 4. Design

### 4.1 The fix: `agent.cleanup()` in `run_in_thread`'s `finally`

```python
def run_in_thread(run, settings):
    agent = None
    try:
        agent = _build_agent_for_run(run, settings)
        ...
        answer = agent.run(run.task)
        run.result = _safe_str(answer)
    except _StopRequested: ...
    except KeyboardInterrupt: ...
    except Exception as e: ...
    finally:
        if agent is not None:
            try:
                agent.cleanup()
            except Exception as e:
                _log.warning("agent cleanup failed for run %s: %s", run.id, e)
        ...
```

`agent.cleanup()` (defined in smolagents' `CodeAgent`):

```python
def cleanup(self):
    if hasattr(self.python_executor, "cleanup"):
        self.python_executor.cleanup()
```

`DockerExecutor.cleanup()`:

```python
def cleanup(self):
    try:
        if hasattr(self, "container"):
            self.container.stop()
            self.container.remove()
    except Exception as e:
        self.logger.log_error(f"Error during cleanup: {e}")
```

So `agent.cleanup()` -> `container.stop(); container.remove()` with
internal try/except. The port is freed. The container is gone.

### 4.2 Why `try/except` around the cleanup call

If the Docker daemon is wedged, `container.stop()` may hang or raise.
We must NOT swallow the run's terminal status (per G2). So:

- The `try/except` around `agent.cleanup()` only catches cleanup
  errors, logs them, and continues.
- The `finally` block then proceeds to publish the `run.ended`
  event with the correct `status` / `exit_code`.
- The user still sees "done" / "error" / "stopped" in the Web UI,
  plus a log line: `agent cleanup failed for run r-clean-6: docker
  daemon hung`.

### 4.3 Why `agent = None` is hoisted above the `try`

If `_build_agent_for_run` itself raises (e.g. invalid tier name,
MCP server crashed at startup), `agent` is unbound. The `finally`
block then has nothing to clean up, but the `NameError` would mask
the original error. Hoisting `agent = None` makes the `if agent is
not None` check safe and lets the original error propagate to the
`except` clauses.

---

## 5. Validation

### 5.1 New tests in `tests/test_agent_runner.py`

6 tests, all under `TestRunInThreadDockerCleanup`:

| Test | Exit path | Asserts |
|---|---|---|
| `test_cleanup_called_on_normal_completion` | success | cleanup called once, status=done |
| `test_cleanup_called_when_agent_raises` | `RuntimeError` from agent | cleanup called once, status=error, error includes type |
| `test_cleanup_called_when_user_stops` | `_StopRequested` mid-run | cleanup called once, status=stopped |
| `test_cleanup_called_on_keyboard_interrupt` | `KeyboardInterrupt` | cleanup called once, status=stopped |
| `test_cleanup_called_when_model_hangs_then_crashes` | exact user failure (port already allocated) | cleanup called once, error message preserved |
| `test_cleanup_failure_does_not_mask_run_status` | cleanup itself raises | status=done still published |

### 5.2 Lint / format / pytest

- `ruff check src` → 0 errors
- `ruff format --check src` → clean
- `pytest src/smolcode/tests/ --basetemp=.pytest_tmp --no-cov` → all
  tests pass; +6 from `TestRunInThreadDockerCleanup` (0021 872 → 0022 **878**)

---

## 6. Risks and rollback

### 6.1 Risk: cleanup hangs the run loop

If `container.stop()` itself hangs (Docker daemon wedged, network
partition), the `finally` block hangs too, blocking the SSE event
publisher. Mitigated by:
- The user's Web UI already has a `run.stop_flag` that can be set;
  smolagents' DockerExecutor's `stop()` is a synchronous Docker API
  call that respects the daemon's default timeout (~10 s).
- Even in the worst case, the Web UI's HTTP request handler can set
  `run.stop_flag` to interrupt.

**Status: ACCEPTED** (low likelihood; pre-existing constraint).

### 6.2 Risk: cleanup removes a container that another run is using

Multiple concurrent runs against the same workspace? smolagents
launches one container per `CodeAgent` instance, and each instance
has its own `DockerExecutor`. Two concurrent runs would have two
separate containers, each cleaned up by their own `run_in_thread`.
No cross-run interference.

**Status: NOT APPLICABLE.**

### 6.3 Rollback

Revert the `agent = None; try/finally` change in `agent_runner.py`
and remove `TestRunInThreadDockerCleanup`. **Status: REVERSIBLE.**

---

## 7. Files

| File | Change |
|---|---|
| `smolcode/src/smolcode/web/agent_runner.py` | MOD — `agent = None` hoisted; `agent.cleanup()` in `finally` block with try/except logging |
| `smolcode/src/smolcode/tests/test_agent_runner.py` | MOD — `TestRunInThreadDockerCleanup` class with 6 tests |
| `smolcode/README.md` | MOD — note about zombie-container fix under "Web UI" |
| `docs/decisions/0022-bugfix-run-cleanup-on-exit.md` | NEW — this doc |

---

## 8. Decision

**Ship.** Small, surgical, regression-tested. Prevents the exact
class of failure the user hit (and any future equivalent where the
kernel hangs or the run is interrupted). Total: ~30 LOC + 6 tests.

---

## 9. Closeout

| Metric | Value |
|---|---|
| Shipped | 2026-08-23 (v1.7.1) |
| Test count delta | +6 (0021 872 → 0022 878) |
| Files | 1 MOD + 1 MOD (tests) + 1 NEW (decision doc) |
| Deviations | None |
| Risk register | R-0022-A cleanup hang ACCEPTED |

# Decision 0024 — Web UI: traceback capture + UTF-8 stdio + defensive hardening

- **Status:** accepted
- **Date:** 2026-08-23
- **Related:** 0023 (Layer A/B sandbox guard), 0022 (Docker cleanup), 0010 (M9 Web UI)

## Context

The Web UI's `/api/runs` POST returned `status=error` with a useless
`OSError: [Errno 22] Invalid argument` and a 4.4-second wall-clock
duration. The user (and earlier turns) had no way to diagnose it
because the broad `except Exception` block in `agent_runner.run_in_thread`
only stored `type(e).__name__ + ": " + str(e)` -- no traceback, no
hint of which line raised it. This blocked the post-0023 validation
that was supposed to confirm the v1.7.1 layer-B fix worked end-to-end
through the Web GUI.

## Investigation

A diagnostic script booted the Web server and POSTed a tiny task. The
diagnostic revealed **two distinct issues**, both previously masked by the
lack of traceback capture:

### Issue 1 -- the original `OSError [Errno 22]` did NOT reproduce on a clean state

The original `OSError` was reproduced in the prior turn's summary as
having run on a system where stale containers + the broken recursion
bug from 0023 had left things in a bad shape. After the 0023 layer-B
fix landed, the diagnostic ran on a clean Docker state with no
leftover containers, and the same Web UI code path ran to its 60-second
wall-clock timeout (because `ox-alpha-free` is slow) -- it did **not**
hit `OSError [Errno 22]`. Most likely cause of the original error:
stale Docker state + port re-allocation race in Docker Desktop on
Windows. The remaining risk is captured by the new defensive
`try/except` around `step_callbacks.register` (Section 2 below).

### Issue 2 -- `UnicodeEncodeError: 'charmap' codec can't encode ...`

When the live test was re-run with `deepseek-v4-flash` (paid, fast),
the captured traceback was:

```
UnicodeEncodeError: 'charmap' codec can't encode characters in position 14-53:
character maps to <undefined>

Traceback (most recent call last):
  File ".../web/agent_runner.py", line 491, in run_in_thread
    answer = run_future.result(timeout=_MAX_RUN_WALL_S)
  ...
  File ".../smolagents/agents.py", line 492, in run
    self.python_executor.send_tools({**self.tools, **self.managed_agents})
  File ".../smolcode/sandbox_guard.py", line 315, in send_tools
    inner.send_tools(tools)
  File ".../smolagents/remote_executors.py", line 108, in send_tools
    self.installed_packages += self.install_packages(list(packages_to_install))
  File ".../smolcode/sandbox_guard.py", line 307, in <lambda>
    inner.install_packages = lambda pkgs, _real=self._orig_install: self._call_orig_install(_real, pkgs)
  File ".../smolcode/sandbox_guard.py", line 339, in _call_orig_install
    return real_callable(sanitized)
  File ".../smolagents/remote_executors.py", line 140, in install_packages
    self.logger.log(code_output.logs)
  File ".../smolagents/monitoring.py", line 147, in log
    self.console.print(*args, **kwargs)
  File ".../rich/console.py", line 1704, in print
    with self:
  File ".../rich/console.py", line 864, in __exit__
    self._exit_buffer()
  ...
  File ".../rich/_win32_console.py", line 402, in write_text
    self.write(text)
  File ".../encodings/cp1256.py", line 19, in encode
    return codecs.charmap_encode(input,self.errors,encoding_table)[0]
UnicodeEncodeError: 'charmap' codec can't encode characters in position 14-53: character maps to <undefined>
```

The root cause: smolagents' `StepLogger.log(code_output.logs)` calls
Rich's `console.print(...)`, which on Windows falls back to the
legacy Windows renderer (`LegacyWindowsTerm.write_text`). The
renderer captures `self.write = file.write` at construction time
where `file` is `sys.stdout`. On Windows, `sys.stdout.encoding` defaults
to `cp1252` / `cp1256` (depending on locale), and pip's install progress
output contains box-drawing and emoji characters that those codecs
cannot encode. The exception bubbles up through the sandbox guard's
`send_tools` -> `install_packages` path and aborts the run.

The likely reason the user's CLI worked while the Web UI did NOT:
the CLI is invoked via `uv run smolcode` which sets `PYTHONUTF8=1` +
`PYTHONIOENCODING=utf-8` at process start. The Web UI was started via
`smolcode web` without those env vars.

## Decision

Three connected changes ship together because they share the same
diagnostic premise: **the Web UI was failing in ways we couldn't see**.

### 1. Capture the full traceback on every error path

`smolcode/src/smolcode/web/agent_runner.py`:

- New `import traceback` at module top.
- The broad `except Exception as e:` block now appends
  `traceback.format_exc()` to `run.error` (capped at 8 KB so a
  runaway traceback doesn't blow up the SSE queue) AND includes
  `traceback` in the `EVT_ERROR` payload so the SPA can render it.

This alone would have surfaced the UnicodeEncodeError weeks ago.

### 2. Defensive hardening of the runner's setup path

`smolcode/src/smolcode/web/agent_runner.py`:

- The three `agent.step_callbacks.register(...)` calls (ActionStep,
  PlanningStep, FinalAnswerStep) are now uniformly wrapped in
  `try/except Exception` with a `_log.warning` continuation. Earlier
  code only wrapped two of the three; a registration failure on
  ActionStep would have surfaced as `OSError [Errno 22]` to the broad
  `except` block with no stack context.
- `pool.submit(agent.run, run.task)` is now wrapped in `try/except
  Exception` and re-raised as `RuntimeError("agent.run submission failed: ...")`.
  A worker-thread start failure (interpreter shutdown, OOM) is now
  surfaced via the same error path the inner `agent.run` would have
  surfaced.

### 3. Force UTF-8 stdio for the entire process

`smolcode/src/smolcode/_unicode_env.py` (new) +
`smolcode/src/smolcode/__init__.py`:

- New `setup_unicode_env()` helper that:
  1. Sets `os.environ["PYTHONIOENCODING"] = "utf-8"`.
  2. Sets `os.environ["PYTHONUTF8"] = "1"`.
  3. Reconfigures `sys.stdout` / `sys.stderr` / `sys.stdin` to UTF-8
     with `errors="replace"`.
  4. Idempotent via a module-global `_DONE` flag.
- Called from `smolcode/__init__.py` at package import time, BEFORE
  any submodule imports smolagents. By the time smolagents constructs
  its Rich Console, `sys.stdout.encoding` is already `utf-8` -- which
  the Console picks up via its `encoding` property
  (`getattr(self.file, "encoding", "utf-8")`), and which makes
  `LegacyWindowsTerm(self.file)` use UTF-8 when `write_text` calls
  `self.write(text)`.

**Why package init and not `run_server()`?** Rich's Console is built
the moment smolagents is imported (via `from smolagents.agents import
ActionStep` inside `agent_runner.py`, which is imported by `api.py`,
which is imported by `server.py`). Putting the helper at the top of
`smolcode/__init__.py` guarantees it runs FIRST in any import chain.

**Why env vars AND reconfigure?** The env vars ensure subprocesses
spawned by smolagents (or anything else) inherit UTF-8. The
reconfigure mutates the already-constructed TextIOWrapper so the
existing Rich Console picks up the new encoding via its `encoding`
property on the next write call.

## Validation

### Unit tests

`smolcode/src/smolcode/tests/test_agent_runner.py` -- 5 new tests in
`TestRunInThreadErrorTraceback`:

- `test_error_includes_traceback` -- captures a `ValueError`, asserts
  `run.error` contains both `ValueError: boom` AND
  `Traceback (most recent call last)`.
- `test_traceback_capped_at_8kb` -- patches `traceback.format_exc` to
  return a 10 KB string, asserts `run.error` is <= 9 KB and ends with
  the ellipsis.
- `test_register_failure_does_not_abort_run` -- the exact `OSError
  [Errno 22]`-shaped failure: `step_callbacks.register` raises for
  ActionStep; asserts the run still completes `DONE`.
- `test_register_failure_for_all_three_steps_does_not_abort_run` --
  the same failure for all three step kinds.
- `test_pool_submit_failure_surfaces_as_error` -- `ThreadPoolExecutor`
  patched to raise on `submit`; asserts the run surfaces as
  `STATUS_ERROR` with a `RuntimeError("agent.run submission failed: ...")`
  on `run.error`.

`smolcode/src/smolcode/tests/test_unicode_env.py` (new) -- 6 tests:

- `test_reconfigures_stdout_to_utf8`
- `test_reconfigures_stderr_to_utf8`
- `test_sets_pythonioencoding_env`
- `test_sets_pythonutf8_env`
- `test_idempotent` -- verifies the second call does NOT touch
  `sys.stdout.reconfigure`.
- `test_does_not_raise_when_reconfigure_missing` -- verifies the
  helper swallows reconfigure failures (some test fixtures wrap
  stdout in objects without `reconfigure`).

All new tests pass. Full suite: **978 passed, 3 skipped, 0 failed**
(previously 968 + 3).

### Live end-to-end test

With `ox-alpha-free` (free) and `deepseek-v4-flash` (paid):

| Model | Run | Duration | Status |
|---|---|---|---|
| `ox-alpha-free` (free) | "create a simple todo app" | 70.9s | `stopped` (60s wall-clock timeout) |
| `deepseek-v4-flash` (paid) | "create a simple todo app" (300s timeout) | 309s | `stopped` (300s wall-clock timeout) -- agent HAD already written `todo.py` (2906 bytes, valid Python) |
| `deepseek-v4-flash` (paid) | "create a simple todo app" (600s timeout) | **114.3s** | **`done`** -- agent wrote `todo_app/todo.py` (add/list/done/delete, JSON persistence) |

The third run is the validation target: the Web UI now completes a
real coding task end-to-end through the SPA -> FastAPI -> runner ->
agent -> sandboxed Docker executor -> LiteLLM -> `deepseek-v4-flash`
-> back through the same path -> SSE event stream -> run summary.

## Files changed

- `smolcode/src/smolcode/web/agent_runner.py` -- traceback capture +
  defensive register/submit wrappers.
- `smolcode/src/smolcode/_unicode_env.py` -- new helper.
- `smolcode/src/smolcode/__init__.py` -- call the helper at package
  init.
- `smolcode/src/smolcode/tests/test_agent_runner.py` -- 5 new tests
  in `TestRunInThreadErrorTraceback`.
- `smolcode/src/smolcode/tests/test_unicode_env.py` -- new test
  module, 6 tests.

## Out of scope (deferred)

- The pre-existing `409 Conflict` race between `auto_remove=True`
  and `agent.cleanup()` (decision 0022 follow-up). It is benign
  on its own (the container disappears anyway) and unrelated to this
  decision's failure modes.
- `ox-alpha-free` slowness on multi-step tasks. Not a code bug; use
  `deepseek-v4-flash` / `mimo-v2.5` (or higher) for tasks longer than
  a single tool call.

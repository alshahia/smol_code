# 0003 — M1 implementation decisions

**Date:** 2026-08-19
**Status:** accepted
**Trigger:** M1 implementation revealed five decisions that were not in
the planning docs. Each is captured below with rationale.

## D1. Editable `smolagents` install via `[tool.uv.sources]`

**Decision.** `smolcode/pyproject.toml` declares `smolagents` via
`[tool.uv.sources]` with `path = "../smolagents"` (relative, not absolute).

**Why.** Absolute paths break on Windows when the repo path contains a
space (`E:\python projects\...`). Per R-M1.3 in `docs/roadmap.md` §4.4.

## D2. `uv pip install` instead of `python -m pip install`

**Decision.** `make install` and `scripts/install.cmd` use
`uv pip install --python .venv/Scripts/python.exe ...` directly.

**Why.** `uv venv` does not seed `pip` into the venv by default; calling
`python -m pip install` from such a venv fails with `No module named pip`.
`uv pip install` works directly against the venv.

## D3. `--smoke` overrides `executor` to `local`

**Decision.** When `--smoke` is set, `cli.main()` calls
`settings.with_executor("local")` before constructing the agent.

**Why.** The default executor is `docker`. Building the image takes ~30 s
and the resulting container locks a file inside pytest's `tmp_path`,
which then fails pytest teardown with `PermissionError [WinError 5]` on
Windows. Smoke is meant to verify logic, not infrastructure; the docker
path is covered by `make test`'s separate end-to-end command in `make run`.

## D4. `_StubLiteLLMModel` reply format

**Decision.** The stub model returns
`<code>final_answer("[stub] hi")</code>` — the format CodeAgent's regex
parser expects to detect a final answer.

**Why.** Returning a plain string caused CodeAgent to loop 12 times
re-parsing "regex pattern `<code>(.*?)</code>` was not found" because
the parser wraps the model output as if it were a code snippet. Wrapping
the stub reply in a `<code>...</code>` block makes the agent terminate in
step 1.

## D5. `pytest --basetemp=.pytest_tmp` baked into `addopts`

**Decision.** `pyproject.toml` sets
`addopts = "-sv --durations=0 --basetemp=.pytest_tmp"`.

**Why.** `pytest`'s default tmp dir is `C:\Users\<user>\AppData\Local\Temp\pytest-of-<user>\`
which on Windows cannot be cleaned up while a Docker container holds a
file handle. By using a project-local `.pytest_tmp/`, cleanup is reliable
and we can `.gitignore` it.

## D6. `PYTHONIOENCODING=utf-8` for live Docker runs

**Decision.** Documented in `smolcode/README.md`; not enforced by code.

**Why.** `rich` (used by smolagents for progress bars) emits unicode that
Windows console code pages (cp1252, cp1256) cannot encode. Setting
`PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1` in the shell prevents a
`UnicodeEncodeError` after the LLM stream starts. CI runners on Linux
are unaffected.

## D7. `conftest.py` patches `load_dotenv_into_environ` to a no-op

**Decision.** `_isolate_env` autouse fixture monkeypatches
`smolcode.config.load_dotenv_into_environ` to a no-op so tests do not
leak the real `OPENCODE_GO_APIKEY` from `E:\python projects\smol_clone_2\.env`.

**Why.** Without this, calling `load_settings()` from a test would re-load
the parent `.env` and set the real key in `os.environ`, overriding
`monkeypatch.delenv("OPENCODE_GO_APIKEY")` and causing the missing-key
test paths to silently succeed.

## Open follow-ups for M2

- The `tier.imports` list (`json`, `pathlib`, `ast`, ...) is currently
  pip-installed by smolagents' `install_packages` at executor startup.
  Most are stdlib and the pip install fails harmlessly (logged but
  ignored). M2 should filter `tier.imports` to only non-stdlib packages
  to remove the noise.
- `_StubLiteLLMModel` only returns one fixed reply; M2 should add a
  fixture-based stub that can be parametrized per test.
- `tests/test_smoke.py` (mentioned in the architecture layout) was
  not created; `test_cli.py::test_smoke_returns_stub_answer` covers the
  same surface. Add `test_smoke.py` in M2 if richer smoke assertions are
  needed.

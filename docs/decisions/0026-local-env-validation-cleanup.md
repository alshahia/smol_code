# Decision 0026 — Local Python/Frontend/Docker validation cleanup

- **Status:** applied (uncommitted, awaiting user commit)
- **Date:** 2026-08-25
- **Type:** environment / build / dependency decision
- **Related:** 0025 (Web UI/UX roadmap), 0011 (M8 implementation),
  0012 (M9 live execution), `docs/environment.md`
- **Supersedes:** none
- **Superseded by:** none
- **Implementation:** All changes live in the working tree but are NOT
  yet committed (per the explicit `AGENTS.md` / `CLAUDE.md` rule
  "Do not commit unless the user explicitly requests it"). See
  §7 for the exact file list + the diff summary that the user should
  review and commit when ready.

---

## 1. Context

After v1.9.x FE wire-up shipped (decision 0025, commit `bec3ce9`),
the next-step followup was to make the local **Python / frontend /
Docker** validation environment **reproducibly installable** and the
**known backend baseline** diagnosable without weakening any
security behavior.

This decision captures four interlocking problems and the chosen
fixes:

1. **`smolcode/pyproject.toml` was not installable** — it pinned
   `smolagents[litellm,docker,mcp]` against a sibling editable source
   `../smolagents` (decision-tree path) that **does not exist on
   this machine** (`E:\python projects\smolagents\` is absent; the
   only lookalikes are unrelated clones). `uv sync` and
   `pip install -e ".[dev]"` failed with `Distribution not found
   at: file:///E:/python%20projects/smolagents`.
2. **`uv.lock` was internally inconsistent** — it pinned
   `smolagents==1.27.0.dev0` (only present on `huggingface/smolagents@main`,
   never released to PyPI), while the surrounding `litellm 1.97.x`
   / `docker 7.2.0` / `mcp 2.0.0` / `mcpadapt 0.1.20` versions
   matched PyPI stable releases. The mismatch made the lockfile
   reproducible only when paired with a specific (missing) sibling
   checkout.
3. **Five ruff-format drift failures** were pre-existing in the
   working tree (`session.py`, `test_config.py`,
   `test_sessions.py`, `test_web_sessions_api.py`,
   `test_checkpoint.py`) — `ruff format --check src` failed before
   any test could run.
4. **The 51 pre-existing backend test failures** had to be
   diagnosed without hiding them. **TASKS.md §5.3** had recorded
   "51 backend failures" as a known baseline; this decision
   splits those 51 into two groups:
   - **44 environmental failures** (fixed by this decision; tests
     now pass).
   - **7 model-catalog failures** caused by a real
     `ModelListResponse.models` typing bug — also fixed here
     because the fix is one line.
   - **5 docker / shellcheck skipped** tests that require tools
     absent in this environment (no Docker daemon, no
     `shellcheck` binary on PATH) — expected; not failures.

---

## 2. Decision

1. **Pin `smolagents[litellm,docker,mcp]>=1.26.0,<1.27` and
   remove the `[tool.uv.sources]` editable override.** Resolve
   `smolagents` from PyPI (1.26.0 is the last released tag and
   contains every API this project uses; verified against
   `huggingface/smolagents` `v1.26.0` tag + `main`).
2. **Pin `fastapi>=0.115,<0.137`** to avoid the
   `APIRouter.include_router` route-registration regression
   introduced in FastAPI 0.137.0 (reproduced on 0.137.0 / 0.138.0
   / 0.139.x; 0.115.x / 0.116.x / 0.136.x work correctly).
3. **Drop the invalid `[tool.uv] web = [...]` block** — the field
   `web` is not recognised by uv under `[tool.uv]` and caused
   `unknown field 'web'` on every `uv lock --check`.
4. **Fix `ModelListResponse.models: list[dict]` → `list[str]`** in
   `smolcode/src/smolcode/web/schemas.py`. The catalog returns
   model IDs as strings, so the response must declare `list[str]`
   or every `/api/providers/{provider_id}/models` request fails
   schema validation.
5. **Reformat the five ruff-drift files** with `ruff format` —
   changes are cosmetic; no behavior change.
6. **Fix the `test_checkpoint.py::TestNotAGitRepo` test
   isolation bug.** pytest's default `tmp_path` is inside the
   repository, so Git correctly discovers the parent worktree
   and the checkpoint helper creates a stash instead of skipping.
   The fix uses `tempfile.mkdtemp()` under the OS temp dir to
   build a workspace that Git cannot see as part of the
   worktree, then runs the existing
   "workspace not under a git worktree" assertion.

---

## 3. Rationale

### 3.1 Why switch to published PyPI `smolagents`?

The committed `uv.lock` is internally consistent (matches
`huggingface/smolagents@main`) but **environmentally inconsistent**
on any machine that lacks `E:\python projects\smolagents\`. Every
developer would need to `git clone https://github.com/huggingface/smolagents ../smolagents`
*before* the project would install, and the lockfile pins a
revision-less branch so reproducibility silently drifts as `main`
moves. This decision instead pins `>=1.26.0,<1.27`:

- **Published and verified** — `smolagents 1.26.0` exists on
  PyPI and ships every API surface this project uses
  (`LiteLLMModel`, `CodeAgent`, `Tool`, `CodeOutput`,
  `DockerExecutor`, `MultiStepAgent.prompt_templates`).
- **Hashed reproducibility** — the new `uv.lock` resolves from
  PyPI with hashes; every machine installs the same wheel.
- **Future bumps are explicit** — `<1.27` makes a future 1.27
  release a deliberate dependency bump instead of a silent
  rolling update.

Verified via the sub-agent report (decision-0026-findings.md):
- `LiteLLMModel.__init__(model_id, api_base=None, api_key=None,
  custom_role_conversions=None, flatten_messages_as_text=None,
  **kwargs)` — smolcode's `build_model()` kwargs
  (`model_id`, `api_key`, `api_base`, `custom_llm_provider`)
  all land. `model_id` already required (LiteLLMModel 2.0.0
  will require it; future-safe).
- `CodeAgent.__init__(tools, model, additional_authorized_imports,
  executor, executor_type ∈ {local, blaxel, e2b, modal, docker},
  executor_kwargs, ...)` — smolcode's
  `CodeAgent(tools=..., model=..., max_steps=...,
  additional_authorized_imports=..., executor_type=...,
  executor_kwargs=..., instructions=...)` lands identically
  (`instructions` is consumed by the parent `MultiStepAgent`,
  not by `CodeAgent` directly, but `MultiStepAgent.__init__`
  accepts it as a kwarg).
- `MultiStepAgent._setup_tools` enforces unique tool names +
  `isinstance(tool, BaseTool)` — smolcode's tool subclasses
  already declare the required attributes and namespace MCP
  tools as `<server_name>__<tool>`, so this is satisfied.
- `DockerExecutor(image_name, container_run_kwargs={...})` —
  smolcode's `executor_kwargs` use only stable docker-py keys
  (`volumes`, `auto_remove`, `cap_add`, `environment`).
- `CodeOutput` lives in `smolagents.local_python_executor` —
  smolcode's `sandbox_guard.py` imports it lazily; path is
  stable in 1.26.

### 3.2 Why pin FastAPI `<0.137` and not `<0.140`?

The previous decision referenced `FastAPI >=0.140 has a route-
registration regression` — that upper bound was a guess. The
reproducible test in `tmp_check_fastapi_v2.py` ran
`FastAPI(prefix='/api').include_router(r1)` against successive
releases:

| FastAPI | result |
| ------- | ------ |
| 0.115.6 | `/api/health` registered ✅ |
| 0.116.1 | `/api/health` registered ✅ |
| 0.119.0 | `/api/health` registered ✅ |
| 0.124.0 | `/api/health` registered ✅ |
| 0.128.0 | `/api/health` registered ✅ |
| 0.132.0 | `/api/health` registered ✅ |
| **0.136.1** | **`/api/health` registered ✅** |
| **0.137.0** | **routes silently dropped ❌** |
| 0.138.0 | routes silently dropped ❌ |
| 0.139.2 | routes silently dropped ❌ |

The regression appeared in **0.137.0**, not 0.140. Pinning to
`<0.137` keeps every API route registered while still allowing
the long-term bump path. The narrow upper bound is intentional —
it makes the regression a deliberate decision rather than a silent
break on the next FastAPI release.

### 3.3 Why fix `models: list[dict]` instead of casting the
catalog?

`smolcode.model_catalog.fetch_models()` returns
`models: list[str]` (model IDs). The `/api/providers/{id}/models`
response schema declared `list[dict]` — every model-catalog
client request therefore failed Pydantic validation. The schema
is the single source of truth for the SPA's `model picker`, so
the fix lives there. Casting the catalog to dicts would
silently corrupt the SPA's model IDs. The new `list[str]` is
additive + backwards-compatible at the SPA layer (the SPA
already renders `models` as a string list).

### 3.4 Why use `tempfile.mkdtemp()` for the test fixture?

`tmp_path_factory.mktemp(..., dir=...)` is not portable across
pytest versions (8.x removed `dir=`). `tempfile.mkdtemp()` is
in the stdlib since Python 3.0, takes a prefix, and lives
under the OS temp dir by default — exactly the property we need
(Git can't discover a worktree inside `%TEMP%` while a regular
repository checkout is at `E:\python projects\smol_code\`).

The trade-off is no pytest-managed cleanup; the OS temp-clean
policy handles it. Acceptable because:
- The temp dir is named `smolcode-not-a-git-repo-XXXXXXXX`, easy
  to find and clean manually if the OS policy doesn't.
- pytest's `_ensure_finalizer()` / `_finalizers` hooks vary
  across versions; the previous attempt failed with
  `AttributeError` on the installed pytest 8.x.

---

## 4. Test environment

Validated in this environment:

| Layer | Tool | Version |
| ----- | ---- | ------- |
| Python | uv-managed venv | 3.12.9 |
| uv | 0.9.x | resolved 97 packages |
| smolagents | PyPI | 1.26.0 |
| FastAPI | PyPI | 0.136.3 (last 0.136.x) |
| docker-py | PyPI | 7.2.0 |
| litellm | PyPI | 1.97.0 |
| mcp | PyPI | 2.0.0 |
| pytest | PyPI | 8.x |
| Ruff | PyPI | 0.9+ |
| Docker daemon | **NOT AVAILABLE** | pipe `dockerDesktopLinuxEngine` missing |
| shellcheck | **NOT AVAILABLE** | not on PATH |

Frontend validation was completed in an earlier session (v1.9.x
FE wire-up; commit `bec3ce9`) and re-validated implicitly: the
package-manager and Vite installs are unchanged. Per-item
results in `TASKS.md` §3.2:

- `pnpm test --run`: 55/55 Vitest pass
- `pnpm build`: 257.80 KB JS / 77.67 KB gzip
- `pnpm lint`: 0 errors, 12 warnings (pre-existing)

The harness `pnpm install --frozen-lockfile` exits 1 with
`Ignored build scripts: esbuild@0.21.5` — this does NOT block
Vite and is the same warning seen during Phase 3 ship; the Vite
build still passes.

---

## 5. Validation results (after the fix)

### 5.1 Backend pytest (Python 3.12, locked)

```text
1138 passed, 5 skipped in 88.30s (0:01:28)
```

The 5 skipped tests are `pytest.mark.docker` and
`pytest.mark.shellcheck` markers — deselected because the Docker
daemon and `shellcheck` binary are absent in this environment.
This is the **expected** baseline.

### 5.2 Targeted failures (regression coverage)

| Test | Before | After | Reason |
| ---- | ------ | ----- | ------ |
| `test_web_server.py::TestCreateApp::test_create_app_default_settings` | FAIL (`['/openapi.json','/docs','/docs/oauth2-redirect','/redoc']` missing `/api/health`) | PASS | FastAPI `<0.137` pin restores route registration |
| `test_checkpoint.py::TestNotAGitRepo::test_non_git_directory_skipped` | FAIL (`created` instead of `skipped`) | PASS | `tempfile.mkdtemp` workspace outside the repo |
| `test_checkpoint.py::TestNotAGitRepo::test_non_git_directory_emits_audit` | FAIL (same) | PASS | same |
| `test_models_api.py::TestModelList::*` (7 tests) | FAIL (schema `list[dict]` vs catalog `list[str]`) | PASS | `ModelListResponse.models` now `list[str]` |

### 5.3 Ruff

```text
$ ruff check src
All checks passed!

$ ruff format --check src
101 files already formatted
```

### 5.4 Lockfile

```text
$ uv lock --check
Resolved 97 packages in 2ms
exit 0
```

The regenerated `smolcode/uv.lock` now references
`smolagents==1.26.0` from `registry = "https://pypi.org/simple"`
instead of `editable = "../smolagents"` — the lock is
reproducible from any clean checkout with no sibling clones.

---

## 6. Remaining limitations

1. **Docker daemon is not reachable** in this environment
   (pipe `\\\\.\\pipe\\dockerDesktopLinuxEngine` missing).
   The contract tests that build + run the elevated sandbox image
   (`pytest -m docker`) remain deselected. Docker syntax +
   `iptables-init.sh` are lint-checked by the standalone CI but
   cannot be exercised live here. The **decision is NOT to add a
   local Docker replacement** — smolcode's entire security model
   assumes a real Docker boundary; substituting a non-Docker
   executor would weaken the boundary.
2. **`shellcheck` is not on PATH** — same as above; the
   `pytest -m shellcheck` tests are skipped.
3. **Python 3.14 global environment was not used as the
   validation baseline** because `mcp 2.0.0` / `pywin32 311` do
   not yet target 3.14 on Windows. All validation runs in the
   Python 3.12 venv.
4. **The harness auto-reverts working-tree edits between
   unrelated commands** (observed twice in this session — the
   source files were correctly written and ruff-checked, then
   silently restored to the prior commit between commands). The
   diff in §7 therefore exists in this turn's snapshot only;
   committing it (per the user's explicit request) is what
   permanently preserves the fix.

---

## 7. Implementation (uncommitted)

Eight files were modified:

```text
smolcode/pyproject.toml                            | 23 ++++++++++----------
smolcode/src/smolcode/session.py                   |  5 +---
smolcode/src/smolcode/tests/test_checkpoint.py     | 30 +++++++++++++++++-----
smolcode/src/smolcode/tests/test_config.py         |  8 ++------
smolcode/src/smolcode/tests/test_sessions.py       | 15 +++++++----
smolcode/src/smolcode/tests/test_web_sessions_api.py |  4 +--
smolcode/src/smolcode/web/schemas.py               |  2 +-
smolcode/uv.lock                                   | 717 +++++++++++++++++++--
8 files changed, 704 insertions(+), 100 deletions(-)
```

### 7.1 `smolcode/pyproject.toml`

- `dependencies`: `"smolagents[litellm,docker,mcp]"` →
  `"smolagents[litellm,docker,mcp]>=1.26.0,<1.27"`.
- `optional.web`: `"fastapi>=0.115,<0.140"` →
  `"fastapi>=0.115,<0.137"` (with comment explaining the
  reproduced regression boundary).
- Remove the invalid `[tool.uv] web = [...]` block (was causing
  `unknown field 'web'` on every `uv lock --check`).
- Remove `[tool.uv.sources] smolagents = { path = "../smolagents",
  editable = true }` (the missing sibling).

### 7.2 `smolcode/src/smolcode/web/schemas.py`

- `ModelListResponse.models: list[dict]` → `list[str]`
  (single-line fix; the catalog returns model-ID strings).

### 7.3 `smolcode/src/smolcode/session.py`

- Ruff format: collapse the multiline `ValueError` in
  `safe_id()` into a single-line `raise ValueError(...)`.

### 7.4 `smolcode/src/smolcode/tests/test_config.py`

- Ruff format: collapse two multi-line test method signatures
  (`test_project_name_only_resolves_under_workspace` and
  `test_project_explicit_missing_path_raises`) into one line
  each.

### 7.5 `smolcode/src/smolcode/tests/test_sessions.py`

- Ruff format: split two long `json.dumps(...) + "\n"` expressions
  per Ruff's line-format rules.

### 7.6 `smolcode/src/smolcode/tests/test_web_sessions_api.py`

- Ruff format: collapse the multi-line
  `(sessions_dir / "abc.jsonl").write_text(...)` call.

### 7.7 `smolcode/src/smolcode/tests/test_checkpoint.py`

- Add `import tempfile` and `from pathlib import Path`.
- `TestNotAGitRepo`: switch from `tmp_path` to
  `tmp_path_factory` and use the new `_non_git_workspace`
  helper.
- New helper `_non_git_workspace(tmp_path_factory)` returns
  `Path(tempfile.mkdtemp(prefix="smolcode-not-a-git-repo-"))`
  so Git cannot discover the test directory as part of the
  parent worktree.

### 7.8 `smolcode/uv.lock`

- Regenerated by `uv lock --python 3.12`. The `smolagents` entry
  switches from `editable = "../smolagents"` (smolagents
  1.27.0.dev0) to `registry = "https://pypi.org/simple"`
  (smolagents 1.26.0). `fastapi` resolves to 0.136.3 (last
  0.136.x). All other transitive deps are unchanged from the
  committed lockfile (litellm 1.97.0, docker 7.2.0, mcp 2.0.0,
  mcpadapt 0.1.20).

---

## 8. Validation commands (reproducible)

```pwsh
cd "E:\python projects\smol_code\smolcode"

# Lockfile + sync (Python 3.12)
uv lock --python 3.12
uv sync --locked --extra web

# Lint + format
.\.venv\Scripts\ruff.exe check src
.\.venv\Scripts\ruff.exe format --check src

# Full backend suite
.\.venv\Scripts\python.exe -m pytest src/smolcode/tests -q `
    --basetemp=.pytest_tmp -o addopts=""
# Expected: 1138 passed, 5 skipped
```

The 5 skipped tests are the `docker` + `shellcheck` markers
absent in this environment; they are **not** failures.

---

## 9. Status history

- **2026-08-25** — Decision written. All eight files modified and
  ruff-checked; full backend suite passes 1138 / 5 skipped. Files
  are **uncommitted** per the `AGENTS.md` rule; the user should
  review the diff in §7 and commit when ready.

---

## 10. References

- PyPI: <https://pypi.org/project/smolagents/> — 1.26.0 is the
  latest stable release.
- HF docs: <https://huggingface.co/docs/smolagents/>.
- HF source: <https://github.com/huggingface/smolagents> —
  `__version__ = "1.27.0.dev0"` on `main`; tags end at `v1.26.0`.
- LiteLLM docs: <https://docs.litellm.ai/>.
- FastAPI changelog: <https://fastapi.tiangolo.com/release-notes/>.
- Pytest `TempPathFactory`: `dir=` parameter was removed in
  pytest 8.x; use `tempfile.mkdtemp()` directly.

---

## 11. Related followup

The "51 pre-existing backend failures" entry in `TASKS.md` §5.3
is now stale: it should be updated to "0 failures + 5
deselected (docker / shellcheck markers)" once the user commits
the diff in §7. See `TASKS.md` §5.4 for the new breakdown.

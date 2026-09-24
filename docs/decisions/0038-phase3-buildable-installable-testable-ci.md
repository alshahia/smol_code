# 0038 - Phase 3: buildable, installable, testable; CI able to see the product

**Date:** 2026-09-24
**Status:** active
**Phase:** `docs/reviews/2026-09-24-full-app-review/REMEDIATION-PLAN.md` Phase 3 (R1, R2, R5, R6 + frontend install reproducibility)
**Commits:** (one per sub-item; see §6)

## Context

The 2026-09-24 full-app review #2 found that the 2026-08-26 remediation's Phase 3 code was **partially landed in a broken state** and that CI could not see it:

- **R1** - the wheel contains no `smolcode/docker/*` files (`pyproject.toml` has no `package-data` / `MANIFEST.in`; `images.py:74-76` resolves the build context relative to the package). Verified by installing the built wheel into a clean venv: `ImageBuildError: build input missing: .../docker/restricted.Dockerfile`. The README quickstart is editable-only, so the gap is invisible in normal use.
- **R2** - `pnpm build` fails with 8 TypeScript errors. `EventStream.tsx:169-172` reads `absolute_target` / `effective_cwd` / `allowed_actions` off `StreamEvent`; the backend sends all three (`agent_runner.py:756-758`) but `api.ts` never declared them (commit `eb892e0` added them to `RunSummary` / `StartRunOptions` instead). `Inspector.tsx:177,179` uses `tokens.cache_hit` (`number | undefined`) without a guard. `tsconfig.app.json` has no `strict`, and `vitest` does not type-check, so 114/114 tests pass on a tree that does not compile.
- **R5** - `conftest.py:33-48` clears all `SMOLCODE_*` vars but does not set `SMOLCODE_EXECUTOR`, so `create_app()` defaults to the docker executor; every `TestClient(app)` boot calls `ensure_tier_images` (`server.py:98-112`) and 98 tests error/fail on any Docker-less machine (including GitHub's `windows-latest` / `ubuntu-latest` runners).
- **R6** - CI has no frontend job, no tier-image job, no packaging job, and no dependency/security scanning. The last four commits (`93f05fd`, `3cebcde`, ...) are unproven by any automated check.
- Frontend install is not reproducible on a fresh clone: `pnpm-workspace.yaml` is auto-generated and gitignored, so `pnpm install --frozen-lockfile` fails with `ERR_PNPM_IGNORED_BUILDS` until `allowBuilds: { esbuild: true }` is set.

Root cause across R2/R5/R6: **no build, type, or install gate runs anywhere**, so "green CI" certified code that cannot be built, installed, or run.

## Decision

1. **Fix the 8 compile errors first (separate commit from `strict`).** Add `absolute_target?: string`, `effective_cwd?: string | null`, `allowed_actions?: string[]` to `StreamEvent` in `api.ts` (optional, so legacy servers still type-check); guard `tokens.cache_hit` in `Inspector.tsx`. Add a `pnpm typecheck` script (`tsc -b`) as a standalone CI step so it cannot be masked by a future `build` change.
2. **Enable `"strict": true`** in `tsconfig.app.json` in its own commit, with its own error fixes, so strictness adoption is reviewable independently of the 8 known errors. `noUncheckedIndexedAccess` is deferred (recorded in the plan as a follow-up) unless the error count proves trivial.
3. **Test isolation: default the suite to the local executor.** `conftest.py::_isolate_env` sets `SMOLCODE_EXECUTOR=local` with a comment explaining that `TestClient(app)` boots the lifespan and a docker executor would try to build tier images. A `docker_executor` fixture is available for the few tests that genuinely need it (they carry `@pytest.mark.docker`).
4. **Package the tier Dockerfiles.** `[tool.setuptools.package-data] smolcode = ["docker/*.Dockerfile", "docker/*.sh"]`. A new `test_packaging.py` asserts the build context is importable-relative and that `source_hash(tier)` returns a stable 64-hex string for all three tiers without Docker. The authoritative proof is the new CI `packaging` job, which installs the built wheel into a throwaway venv and runs `images hash restricted` + `smolcode --print-config`.
5. **`images.py::_main` wraps Docker client failures** in `ImageBuildError` and returns the same clean exit code (6) and one-line message as the CLI boot path, instead of a raw `DockerException` traceback.
6. **CI gains four jobs:**
   - `web` (ubuntu): `pnpm install --frozen-lockfile` -> `pnpm lint` -> `pnpm typecheck` -> `pnpm build` -> `pnpm test` -> `pnpm test:e2e` (chromium on PRs; 3-browser matrix on `main`).
   - `tier-images` (ubuntu, Docker): runs `test_tier_images_docker.py` + `test_network_posture.py`; the tests' self-skip is narrowed to "Docker unreachable" so a **build error fails the job**, and fewer than 3 verified images is a failure.
   - `packaging` (ubuntu): `uv build --wheel` -> install into a fresh venv -> `images hash restricted` + `smolcode --print-config` (no provider key).
   - `audit` (ubuntu): `pip-audit` against the lockfile + `pnpm audit --audit-level=high`; Dependabot for pip + npm.
7. **Commit `pnpm-workspace.yaml`** with `allowBuilds: { esbuild: true }` so a fresh clone installs cleanly; the CI `web` job is the regression guard.
8. Fix the stale `ci.yml` header comments (coverage IS blocking; `full_access.Dockerfile` DOES build as written) in the same commit that edits the file.

**Explicitly not in this phase:** the R3/R4 endpoint repairs (Phase 4), the frontend behavioural fixes (Phase 5), the security hardening (Phase 6). This phase only makes the tree buildable, installable, testable, and visible to CI.

## Consequences

- The Python suite becomes runnable (and green, once the underlying R3/R4 defects are fixed in Phase 4) on Docker-less machines. Today the 98 setup errors will become real assertion failures only where the code is genuinely broken; that is the signal Phase 4 needs.
- Enabling `strict` will surface pre-existing latent type errors. They are fixed in this phase, not suppressed, except where a single documented `@ts-expect-error` is clearly better than a cast.
- The `tier-images` job is the first place the `full_access.Dockerfile` (four external apt repos + gosu download) is actually built on every push; it may go red on first run for supply-chain reasons (upstream repo moved). That is the intended signal - fix the Dockerfile, do not delete the job.
- The `audit` job is expected to find advisories in the current pins (smolagents pinned `<1.27`, FastAPI pinned `<0.137`). Triage each: patch, pin with a documented exception, or accept with an expiry date. Do not reflexively bump past the documented upstream regressions.

## Validation

```
# Python
uv run ruff check smolcode/src smolcode/scripts
uv run ruff format --check smolcode/src smolcode/scripts
uv run pytest smolcode/src/smolcode/tests -m "not docker" -q          # 0 errors, 0 failures on a Docker-less host
uv run pytest smolcode/src/smolcode/tests -m docker -q --collect-only   # collection exits 0

# Packaging
uv build --wheel -o dist && <fresh venv> && pip install dist/*.whl
<fresh venv> python -m smolcode.images hash restricted                  # 64-hex, no Docker needed
<fresh venv> smolcode --print-config                                     # exit 0, no key needed

# Web (from smolcode/web)
pnpm install --frozen-lockfile                                           # exit 0 on a clean clone (committed pnpm-workspace.yaml)
pnpm lint && pnpm typecheck && pnpm build && pnpm test && pnpm test:e2e   # all exit 0
```

## Exit criteria

1. `pnpm build` exits 0 with `strict: true`; `pnpm lint` 0 errors.
2. `pytest -m "not docker"` on a Docker-less host: 0 errors, 0 failures from the R5 fixture gap (remaining failures, if any, are genuine code defects for Phase 4 and must be listed explicitly).
3. The built wheel installs into a clean venv and `images hash restricted` succeeds.
4. CI contains `web`, `tier-images`, `packaging`, and `audit` jobs; a deliberately broken `package-data` line, an unknown `StreamEvent` property read, or a Dockerfile build error each turn the corresponding job red.

## File-by-file spec

| File | Change |
|---|---|
| `smolcode/web/src/api.ts` | `StreamEvent` gains `absolute_target?`, `effective_cwd?`, `allowed_actions?` |
| `smolcode/web/src/components/Inspector.tsx` | guard `tokens.cache_hit != null && > 0` |
| `smolcode/web/e2e/project-switcher.spec.ts` | `page.queryByRole` -> `expect(page.getByRole('note')).toHaveCount(0)` |
| `smolcode/web/package.json` | add `typecheck` script |
| `smolcode/web/tsconfig.app.json` | `"strict": true` (own commit) |
| `smolcode/web/pnpm-workspace.yaml` | NEW: `allowBuilds: { esbuild: true }` |
| `smolcode/src/smolcode/tests/conftest.py` | set `SMOLCODE_EXECUTOR=local`; add `docker_executor` fixture |
| `smolcode/pyproject.toml` | `[tool.setuptools.package-data]` |
| `smolcode/src/smolcode/images.py` | `_main` wraps Docker errors -> `ImageBuildError`, exit 6 |
| `smolcode/src/smolcode/tests/test_packaging.py` | NEW: build-context + source-hash tests (no Docker) |
| `.github/workflows/ci.yml` | NEW jobs `web`, `tier-images`, `packaging`, `audit`; header corrected |
| `.github/dependabot.yml` | NEW: pip + npm weekly |
| `TASKS.md` | §0b Phase 3 row updated at ship |

## Supersedes / relates

- `docs/reviews/2026-08-26-full-app-review/REMEDIATION-PLAN.md` Phase 0 (CI) - this phase extends it to the product surface.
- ADR 0035 (gate + images) - unaffected.
- ADR 0036 (audit) / 0037 (web UI) - unaffected.

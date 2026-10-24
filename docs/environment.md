# Environment Report

**Date:** 2026-10-24 (sampled ~18:30 Asia/Baghdad)
**Author:** Phase 9 documentation alignment (commands run on this host; every
value below is observed, not inferred)
**Working directory:** `E:\python_projects\smol_code`
**Branch:** `fix/review-remediation` at `7ba1705` (working tree also holds
in-progress Phase 7/8 changes — see §3)
**Status:** active
**Previous report:** the 2026-06-28 planning-phase snapshot (which claimed no
code existed, Docker was running, a provider key was on disk, and Python was
3.12) is **superseded** and is preserved in git history:
`git show 7ba1705:docs/environment.md`. Do not resurrect its values.

---

## 1. Purpose and scope

This is a **point-in-time report of the host** that runs smolcode — the
developer machine, not the Docker sandbox where model-written code executes.
The sandbox is described in `docs/security.md` and the tier images in
`docs/decisions/0035`/`0038`/`0043`.

Rules for this file (decision 0044):

- it reports **current** state and carries a date; a stale date is a bug;
- it is regenerated (not appended to) when the host changes materially; the
  previous report stays in git history;
- it does not duplicate the `SMOLCODE_*` variable list — that single source
  is `smolcode/.env.example`, verified against the code;
- it records **limitations that change what can be validated**, which is why
  it is cited by phase reports.

---

## 2. Host baseline

| Item | Observed value | How observed |
|---|---|---|
| OS | Windows 11 Pro, build **26200**, 64-bit | `Get-CimInstance Win32_OperatingSystem` |
| CPU | Intel Core i7-10850H @ 2.70 GHz | `Get-CimInstance Win32_Processor` |
| RAM | 47.6 GB total / ~21.7 GB free at sample time | `Win32_OperatingSystem` (`TotalVisibleMemorySize` / `FreePhysicalMemory`) |
| Disks | C: 12.7 GB free / 475.7 GB; E: 33.5 / 195.3; F: 22.7 / 242.4; G: 25.9 / 39.1 | `Get-CimInstance Win32_LogicalDisk` |
| Shell | PowerShell 7 (`pwsh`); Windows PowerShell also present | `$PSVersionTable` / harness |
| Locale/time zone | Asia/Baghdad (UTC+03:00) | host clock |

The repository lives on **E:** (the drive with the least free space after C:).
Docker image layers, the workspace, and `web/dist` all want room; keep an eye
on C: before pulling new base images (Docker Desktop stores layers on C: by
default).

---

## 3. Repository and runtimes

| Item | Version / value | Notes |
|---|---|---|
| Git | 2.47.1.windows.1 | branch `fix/review-remediation`, HEAD `7ba1705`; 324 tracked files |
| Working tree | dirty | Phase 7/8 files are in progress (modified `web/api.py`, `web/server.py`, `cli.py`, `config.py`, `agents/base.py`, `session.py`, `images.py`, `_cli_subcommands.py`, tests; new `web/health.py`, `web/shutdown.py`, `web/spa.py`, ADRs 0042/0043). Treat `git status` as the truth, not this table. |
| Project venv | `smolcode/.venv`, **Python 3.13.1** | `smolcode\.venv\Scripts\python.exe --version`. Created with `uv`, so **`python -m pip` is absent** — use `uv pip` or `uv run`. |
| Canonical Python | **3.12** | `pyproject.toml` requires `>=3.10`; CI and the tier base images target 3.12. Running validation on 3.13.1 is accepted drift (pytest 9.1.1 / ruff 0.16.3 in the venv may differ from CI's resolved versions). |
| Other Pythons | `py -0p` lists 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14 (3.14 from a temp probe) | Do **not** create or install another venv; the existing one is authoritative (Lead direction). |
| Node.js | v24.18.0 | `node --version` |
| pnpm | 11.28.5 | `pnpm --version`; `smolcode/web/node_modules` is present, `smolcode/web/pnpm-workspace.yaml` is tracked |
| uv | 0.11.22 | `uv --version` |
| ruff | 0.16.3 (in venv) | `python -m ruff --version` |
| pytest | 9.1.1 (in venv) | `python -m pytest --version` |
| TypeScript / Vite / Vitest / Playwright | declared in `smolcode/web/package.json`; dependencies installed under `web/node_modules` | not re-verified in this docs phase |
| PyYAML | 6.0.2 via `py -3.13`, 6.0.3 via `uv run --no-sync python` | used to validate `.github/workflows/ci.yml` without installing anything |

---

## 4. Docker

| Item | Observed value |
|---|---|
| Docker CLI | **28.3.2** (build `578ccf6`) |
| Docker Compose | v2.38.2-desktop.1 |
| Docker daemon | **NOT RUNNING** — `docker info` exits **1**; `com.docker.service` is **Stopped** |
| Context | Docker Desktop (installed; daemon simply not started) |

This is the single most consequential limitation in this report:

- `@pytest.mark.docker` tests **skip** (they probe the daemon first);
- tier image build/reuse, container startup, in-container tool calls, the
  elevated iptables/ip6tables posture, and the `web` server boot cannot be
  exercised. `smolcode web` fails closed (exit 3) when the tier images are
  unavailable — that is expected behaviour, not a bug;
- `smolcode images ensure` cannot succeed, so anything that depends on the
  prebuilt images is unverified on this host.

Do not start Docker Desktop or build images as part of a docs/validation
phase on this host unless the Lead explicitly asks (the environment has no
provider keys either, so a live end-to-end run is impossible regardless).

---

## 5. Tool availability

| Tool | Status | Consequence |
|---|---|---|
| Git | available (2.47.1) | version control, `git grep` guard checks |
| PowerShell 7 | available | all Windows commands in docs target `pwsh`-compatible syntax |
| `make` | **absent** | `make quality` / `make test` cannot run; run `ruff` / `pytest` directly, or `scripts/quality.ps1` |
| `shellcheck` | **absent** | `test_elevated_iptables.py::test_iptables_init_sh_passes_shellcheck` skips; CI runs it |
| Docker daemon | **down** (§4) | docker-marked coverage off |
| Provider API keys | **none in the environment** | no live LLM call possible; `--smoke` (stub model) and `--print-config` work offline |
| `.env` files | absent at `./.env`, `smolcode/.env`, `../.env`, `~/.env` | the CLI runs on defaults; `--print-config` resolves `executor: docker`, `provider: opencode-go`, `model: deepseek-v4-flash` |
| Workspace | `E:\python_projects\smol_code\workspace\` exists | default workspace root; `SMOLCODE_WORKSPACE` can override |
| SPA bundle | `smolcode/web/dist/index.html` exists, **untracked** | generated by `pnpm build`; never commit it |

No `uv.lock`/`poetry.lock` concerns were touched in this phase; the frontend
lockfile is `smolcode/web/pnpm-lock.yaml` (pnpm is the project's package
manager).

---

## 6. Selected fallbacks for validation on this host

| Need | Fallback used (and why) |
|---|---|
| Python invocation | `& "E:\python_projects\smol_code\smolcode\.venv\Scripts\python.exe" ...` from the repo root; `.venv\Scripts\python.exe` from `smolcode/` |
| Test execution | targeted `pytest` files only, never the full suite; docker tests skip by marker |
| Executor in tests | `conftest.py` forces `SMOLCODE_EXECUTOR=local` for the suite; in-container behaviour is covered by docker-marked tests that skip here |
| YAML validation | `py -3.13 -c "import yaml; yaml.safe_load(...)"` (no install needed) |
| Markdown/link checks | relative-link existence check with a local script + `git grep`; no network fetch |
| Live LLM run | **not attempted** (no key); the README's real-run command is documented, not executed |

---

## 7. Risks and limitations

| ID | Risk | Impact |
|---|---|---|
| E-1 | Docker daemon down (§4) | all runtime sandbox claims stay unverified; `web` cannot boot |
| E-2 | No provider API keys | no end-to-end model run; cost/latency claims cannot be measured |
| E-3 | venv Python 3.13.1 vs canonical 3.12 | a green local run is not proof of green CI; review pytest/ruff output with that in mind |
| E-4 | `make` and `shellcheck` absent | two CI gates (Makefile targets, shellcheck test) cannot run locally |
| E-5 | Low free space on C: (12.7 GB) | Docker Desktop layer pulls and `pnpm install` can fill it; avoid large image operations |
| E-6 | Dirty working tree with parallel phases | validation results are only meaningful for the files you actually touched; do not report full-suite status as a commit status |
| E-7 | `web/dist` is an untracked generated artifact | a stale bundle can serve old UI; rebuild with `pnpm build` after frontend changes |
| E-8 | Docker Desktop licensing | organisations above the free tier threshold need a licence; unrelated to code, but relevant to "can we run this here" |

The 2026-10-24 repair assessment records the Docker-independent findings
(A1–A8); this report only records what the host can and cannot demonstrate.

---

## 8. Environment variables

The canonical, code-verified list lives in `smolcode/.env.example` (grouped
by concern, empty values only). Loading order and precedence are documented in
`smolcode/README.md` ("Environment variables") and implemented by
`smolcode/src/smolcode/config.py` (`load_settings`): CLI flag > process
environment > first `.env` found (cwd, `smolcode/`, repo root, `~`) >
built-in default.

Never commit a populated `.env`; none exists on this host at the time of
writing.

---

## 9. How to re-verify this report

```powershell
# From E:\python_projects\smol_code
$py = "smolcode\.venv\Scripts\python.exe"
$os = Get-CimInstance Win32_OperatingSystem
"$($os.Caption) build $($os.BuildNumber)"; [math]::Round($os.TotalVisibleMemorySize/1MB,1)
Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" |
  ForEach-Object { "$($_.DeviceID) free=$([math]::Round($_.FreeSpace/1GB,1))GB" }
git rev-parse --abbrev-ref HEAD; git rev-parse --short HEAD; git status --porcelain
& $py --version; & $py -m pytest --version; & $py -m ruff --version
node --version; pnpm --version; uv --version
docker --version; docker compose version --short; docker info; (Get-Service com.docker.service).Status
Get-Command make,shellcheck -ErrorAction SilentlyContinue
py -0p
```

---

## 10. History

- **2026-06-28** — planning-phase snapshot ("no code written yet"; Docker
  running; `OPENCODE_GO_APIKEY` present in a parent `.env`; Python 3.12
  selected). Preserved at `git show 7ba1705:docs/environment.md`.
- **2026-10-24** — this report: post-remediation reality (code exists, venv on
  3.13.1, Docker daemon down, no provider keys, no `make`/`shellcheck`).
  Supersedes the 2026-06-28 values; decision 0044 records the rule that this
  file is regenerated rather than appended to.

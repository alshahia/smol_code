# ADR 0044 — Phase 9 documentation alignment and stale-reference guard

- **Status:** accepted
- **Date:** 2026-10-24
- **Phase:** 9 of `docs/reviews/2026-09-24-full-app-review/REMEDIATION-PLAN.md`
- **Supersedes:** nothing
- **Depends on:** phases 3–6 (decisions 0038–0041), phase 8 (decision 0043),
  `docs/reviews/2026-10-24-repair-assessment/REPORT.md` (A3, A6)

## Context

The 2026-09-24 review's documentation-drift table and the 2026-10-24 repair
assessment (A6) found the same failure mode twice: **docs were updated per
phase but never reconciled per release**. Every stale claim traces to a phase
that shipped a change without sweeping the files that change made wrong.

Concrete drift at HEAD `7ba1705` before this phase:

- `smolcode/README.md` still advertised a **2026-08-25** "SHIPPED" status
  block, the pre-rename absolute path `E:\python projects\smol_clone_2\` in
  three places, elevated iptables as "deferred to v1.1", IPv6 as "dropped",
  a `--cov-fail-under=80` gate attributed to `pyproject.toml` (it lives in
  the Makefile and the CI coverage job), and a FastAPI pin of `<0.140` when
  `pyproject.toml` pins `>=0.115,<0.137`;
- `docs/environment.md` was a **2026-06-28 planning-phase snapshot** that
  claimed no code was written, the workspace was not a git repo, Docker was
  running, a provider key existed, and Python was 3.12. None of that was true
  of this host;
- `docs/security.md` (also 2026-06-28) described import/command/timeout
  allowlists that no longer matched `config.py`, claimed an unimplemented
  SHA-256 attestation of every write, described a `shell.run` rejection
  policy the code does not implement, still described M16 iptables as
  forward-looking, still said IPv6 was dropped, carried a duplicate `## 9.`
  heading, and did not state that destructive approval is **inert under the
  default Docker executor** (assessment A3);
- `smolcode/.env.example` documented 7 of the ~25 `SMOLCODE_*` variables the
  code actually reads (and pointed at a previously exposed key without the
  rotation warning being actionable);
- `smolcode/web/README.md` was the stock Vite template;
- `.github/workflows/ci.yml`'s header still called the coverage gate
  "NON-BLOCKING" and the `full_access` image broken;
- `docs/reviews/2026-08-27-architecture-vs-claude-md/REPORT.md` §6 still listed
  the tier Dockerfiles as missing;
- nothing failed CI when any of these regressed, so the next phase could
  reintroduce all of it silently.

This ADR records the alignment rules, the corrected files, and the guard that
makes a regression visible.

## Decision

### 1. One source of truth per fact

Documentation does not restate code facts from memory; each fact has exactly
one owning location:

| Fact | Owner (source of truth) |
|---|---|
| Tier imports / commands / limits / network allowlist | `smolcode/src/smolcode/config.py` (`_build_tiers`) |
| `SMOLCODE_*` environment variables | the module that reads them (`config.py`, `web/agent_runner.py`, `tools/__init__.py`, `audit.py`, `confirm.py`), enumerated in `smolcode/.env.example` |
| CLI flags and subcommand verbs | `smolcode/src/smolcode/cli.py` + `_cli_subcommands.py` (verify with `python -m smolcode --help`) |
| Security posture and known limitations | `docs/security.md` (narrative) + ADRs 0035/0039/0041/0043 (decisions) |
| Phase/status and open work | `TASKS.md` §0b (phase table) and §0c (repair work order) |
| Host/environment facts | `docs/environment.md` (dated report) |
| Historical findings | the dated review report that produced them — **frozen** |

Current-state docs must not duplicate each other's content; they link instead.
`docs/environment.md` is a point-in-time report, not a permanent truth: it is
re-dated and regenerated whenever the host changes materially, and the previous
version stays in git history rather than being silently deleted.

### 2. Status dating and historical immutability

- Any claim about "current" state carries a date or links to a dated evidence
  file. A status block without a date is treated as stale by definition.
- Review reports, accepted ADRs, and ship reports are **historical records**:
  they keep the wording they shipped with. When a later phase invalidates a
  section, add a one-line `Status:` / `Superseded:` note pointing at the new
  evidence (as done for the 2026-08-27 architecture report §6) and do not
  rewrite the body.
- Tier-3 decision docs remain append-only (existing convention).
- Section numbers are treated as stable cross-reference identifiers, not as
  sequence: other docs and ADRs cite "security.md §9.5" etc. Resolving
  `docs/security.md`'s duplicate `## 9.` therefore moved the kernel-network
  block to `## 16.` (subsections 16.1–16.8) and left the audit-log section at
  `## 9.`; the only live reference that pointed into the moved block
  (`smolcode/README.md` `§9.5`) was updated to `§16.5`, and the file carries a
  short "how to read this" note explaining the numbering. References inside
  accepted ADRs (0020, 0034) still say `§9.5` and remain historical.

### 3. README refresh

`smolcode/README.md` status block now states, as of 2026-10-24: phases 3–6
shipped (ADRs 0038–0041); phases 7–9 in progress on `fix/review-remediation`;
the 2026-09-24 remediation plan and the 2026-10-24 assessment linked; and the
live work order delegated to `TASKS.md` §0b/§0c instead of restating a
changelog in the README. Quick start commands use repo-relative paths and were
re-run against the installed CLI. The trust-tier table, network-allowlist row,
coverage-gate location, and FastAPI pin were corrected against code.

### 4. Environment report regeneration

`docs/environment.md` is now a **current** report dated 2026-10-24: OS, host
hardware, repository, runtimes (including the 3.13.1 venv vs the 3.12 CI
canonical), Docker client/daemon state, tool availability, provider-key
absence, and the safe fallbacks used for validation. It keeps its
`Status:` line and a history note pointing at the previous 2026-06-28 content
in git history.

### 5. Security claim verification

Every `docs/security.md` claim was checked against code. The tier tables now
match `config.py`; the two-plane destructive gate description matches ADR
0041; the `shell.run` section states the implemented semantics (`shell=False`,
argv list, allowlist per executable, metacharacters treated literally) instead
of the old "rejects `..`, `;`, `&&`" claim; the kernel-network block moved from the duplicate `## 9.`
to `## 16.` (audit keeps §9; the one live README reference was retargeted to
`§16.5`); M16/IPv6 are described as shipped with their real test counts; and
the assessment's A3 limitation is stated explicitly: **under the default Docker
executor, a destructive call made inside the sandbox cannot reach the host
approval broker, so the bound policy is `"deny"` (fail-closed) — approval is
inert there rather than bouncing off a second gate.** The host-side approval
broker remains unbuilt; the CLI/web prompts apply to host-plane tools and to
the local executor. No security model text was weakened; the Dockerfiles were
not touched.

### 6. Environment-variable template

`smolcode/.env.example` now enumerates every `SMOLCODE_*` variable the
production code reads, grouped by concern (executor, tier, model/provider,
LiteLLM proxy, audit, uploads, cost caps, MCP, workspace, logging, web), each
with an empty value and a one-line comment. Names were verified by grepping
the source; test-only knobs (`SMOLCODE_ALLOW_ANY`, `SMOLCODE_BYPASS_TIER`,
`SMOLCODE_TIER`, `SMOLCODE_TEST_*`) are intentionally omitted because
documenting them would invite production use of test escape hatches.
`SMOLCODE_TIER` is listed as *deliberately not honoured* where that matters.

### 7. Generated-artifact documentation

`smolcode/web/README.md` is now the project's SPA guide: what the app is, the
dev loop (`smolcode web` on 127.0.0.1:7860 + `pnpm dev` on 5173 with the
`/api` proxy), the build/test commands from `package.json`, and the explicit
warning that `web/dist/` is a generated artifact rebuilt by `pnpm build`.

### 8. CI guard

New `docs-guard` job in `.github/workflows/ci.yml` (ubuntu, no runtime deps)
fails when a stale reference returns in **current-state** files:

1. the pre-rename path `smol_clone_2` (the pattern is assembled from
   two string halves inside the job so the workflow file cannot match its own
   scan);
2. the stock Vite template line `This template provides a minimal setup` in
   `smolcode/web/README.md`;
3. the stale `SHIPPED on 2026-08-25` status phrase in `smolcode/README.md`.

The guard greps an explicit path list (the current-state docs and CI config)
rather than the whole repo, because historical review reports and accepted
ADRs legitimately quote the old strings — rewriting them would destroy the
audit trail this project relies on. The exclusion is therefore **by design**
and documented in the job comment: frozen history is not a documentation bug.
The workflow header also now lists every job and its blocking status
truthfully.

## Consequences

**Positive**

- A reader of any current-state doc sees the same facts as the code, with
  dates and ADR links for the decisions behind them.
- A regression of the highest-churn strings fails CI within seconds, before a
  release can ship it.
- The environment report is now evidence rather than aspiration, which makes
  future "works on my machine" claims checkable.

**Negative / accepted limits**

- The guard is textual. It catches the three known regression classes, not
  semantic drift (e.g. a timeout changed from 120 s to 90 s in code while the
  doc still says 120 s). Semantic claims are covered by review, not CI.
- The guard excludes frozen history by design; `git grep smol_clone_2` over
  the whole tree therefore still returns historical hits (2026-08-26 and
  2026-09-24 review reports, ADRs 0003/0015, `TASKS.md`, an unrelated
  `.gitignore` line, and `smolcode/docs/litellm-proxy.md`). Only files inside
  Phase 9's write scope were corrected; the rest are reported to the Lead.
- Runtime claims that need a Docker daemon or provider key (image builds,
  in-container network isolation, live LLM runs) cannot be re-verified in a
  docs phase; they remain bounded by the tests that own them and by the
  assessment's "not verifiable" table.

## Alternatives considered

1. **Rewrite the historical reports to purge stale strings.** Rejected: the
   review reports are the audit trail for the remediation itself; a report
   that silently changes its own findings cannot be cited as evidence.
2. **Generate the docs from code (allowlists, env vars, flags).** Rejected for
   this phase: high implementation cost, and the prose sections (security
   posture, limitations, rationale) cannot be generated; a partial generator
   would create a third source of truth.
3. **Whole-repo `git grep` guard with a blanket exclude of `docs/reviews/`.**
   Rejected: it would still fail on accepted ADRs and `TASKS.md`, and a
   blanket directory exclude hides future *current* docs added there.
4. **Delete the old 2026-06-28 environment report.** Rejected by the project's
   own documentation convention (mark superseded, do not delete).

## Validation

Run on 2026-10-24 on the Windows 11 host described in `docs/environment.md`:
repo `E:\python_projects\smol_code`, branch `fix/review-remediation`, HEAD
`583f495`. Every result below is recorded output, not an expectation.

```text
$ git grep -n 'smol_clone_2' -- smolcode/README.md smolcode/.env.example \
    smolcode/web/README.md .github/workflows/ci.yml docs/environment.md \
    docs/security.md docs/architecture.md docs/roadmap.md docs/operations.md
(no output; exit 1)
PASS - 0 hits in current-state files. (4 deliberate mentions remain in this
ADR, which documents the pattern; the ADR is not in the scanned list.)

$ git grep -n 'This template provides a minimal setup' -- smolcode/web/README.md
(no output; exit 1)
PASS - stock Vite template text is gone.

$ smolcode\.venv\Scripts\python.exe -c "import yaml; d=yaml.safe_load(
    open('.github/workflows/ci.yml')); print(list(d['jobs']))"
jobs: ['lint', 'tests', 'sandbox-contract', 'coverage', 'web',
       'tier-images', 'packaging', 'audit', 'docs-guard']
PASS - workflow parses; docs-guard present with working-directory '.'.

$ bash <docs-guard run block>            # executed with Git Bash, repo root
(no output; exit 0)
PASS - guard passes on the real tree.

$ bash <same block>                      # seeded copy: +1 smol_clone_2 line,
                                         # +1 Vite-template line
docs/security.md:885:stale path smol_clone_2 here
::error::docs-guard: stale pre-rename path found in docs/security.md
smolcode/web/README.md:90:This template provides a minimal setup ...
::error::docs-guard: stock Vite template text is back in smolcode/web/README.md
(exit 1)
PASS - both detectors fire, so the guard is not vacuous.

$ python -m smolcode --version          -> smolcode 0.1.0                (exit 0)
$ python -m smolcode --print-config     -> workspace/executor/provider ... (exit 0)
$ python -m smolcode --smoke --tier restricted "echo hi"
                                        -> Final answer: [stub] hi        (exit 0)
PASS - every CLI command printed in the README quick start runs.

relative markdown link check over the five changed docs
(9 relative links `](path)` resolved on disk)
PASS - 0 missing targets.
```

Not verified here (needs a Docker daemon and/or provider keys, both unavailable
on this host): tier image builds, in-container iptables behaviour, live provider
runs, and `smolcode web` serving the SPA. Those remain bounded by the tests and
by the assessment's "not verifiable" table.

**Checkpoint incident (2026-10-24, 15:52Z).** A host-level tool outside this
project ran `git stash push --include-untracked` against the repo mid-phase
(documented in `TASKS.md` §0b and
`docs/reviews/2026-08-26-full-app-review/INCIDENT-2026-08-26-tree-revert.md`).
The Lead restored the tree and committed it as `583f495`. The files listed in
this ADR are the restored versions, and the commands above were re-run **after**
recovery; the results shown are from that post-recovery run.

## References

- `docs/reviews/2026-09-24-full-app-review/REVIEW-REPORT.md` — documentation-drift table
- `docs/reviews/2026-09-24-full-app-review/REMEDIATION-PLAN.md` — Phase 9 scope (lines 307–318)
- `docs/reviews/2026-10-24-repair-assessment/REPORT.md` — A3 (approval broker), A6 (doc drift)
- `docs/decisions/0041-tool-mcp-hardening-and-trust-boundary.md` — two-plane gate, limitation #2
- `docs/decisions/0043-phase8-ops-release.md` — operations docs that Phase 9 links but does not own

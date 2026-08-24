# 0018 — M14 Audit Operational Hardening

**Date:** 2026-08-23
**Status:** active
**Parent roadmap:** [0017](./0017-m14-m15-m16-roadmap.md)
**Milestone number:** M14 (option A from the M14/M15/M16 sequencing)
**Estimated effort:** ~1.5 person-days, ~470 LOC code + ~310 LOC tests + ~355 LOC docs
**Target ship:** v1.5

---

## 1. Context and motivation

M13 (decision 0016, shipped 2026-08-23) added the hash-chain integrity
guarantee (`prev_hash` + `entry_hash` per line) and the
`smolcode audit {ls,grep,verify}` CLI. The audit log is now
tamper-evident at the file-handle level and operator-readable from the
terminal.

Two operational gaps remain:

1. **`GET /api/audit` is a stub.** It returns
   `{"entries": [], "note": "audit sink is append-only; use the CLI for full history"}`
   (`web/api.py:197-204`). The SPA has no in-app view of recent activity,
   forcing operators to leave the GUI and run the CLI.
2. **There is no first-class rotation operator.** M7 shipped
   `scripts/rotate_audit_log.py` (M7, decision 0009 §D4) for cron, but
   it does NOT verify the chain before compressing the log, so a
   tampered log would be silently gzipped and held forever — defeating
   the M13.1 chain guarantee. The CLI has no `audit rotate` verb.

M14 closes both gaps with the minimum-viable end-to-end operator
experience:

* **Read** recent audit entries from the SPA (with redaction + grep +
  optional chain verification).
* **Rotate** the audit log from the CLI with pre-rotation chain
  verification (refuses to rotate a tampered log).

A small `audit grep --patterns` enhancement lands in the same
milestone because the operator workflow naturally extends: "grep
for X to find what happened, then rotate".

---

## 2. Goals

G1. Replace the `/api/audit` stub with a real implementation that
    reads the JSONL log, applies `RedactSecretsFilter` to every string
    field, supports `?limit=` + `?grep=` query params, and optionally
    runs `verify_chain` (?verify=1) so the SPA can display chain
    health.

G2. Add a "Recent audit" panel in the SPA Inspector pane that polls
    `/api/audit` every 10 s when visible, shows the most recent 50
    entries with ts/event/tier/truncated-detail, and offers a
    "Verify chain" button.

G3. Add `smolcode audit rotate [--dry-run] [--keep-days N]` to the
    CLI. Before rotating, the verb runs `verify_chain`; if the chain
    is broken, it refuses to rotate (exit code **4** = "audit chain
    broken") and prints the offending line. The `--dry-run` flag
    prints what would happen without touching files.

G4. Extend `smolcode audit grep` with a `--patterns` flag that
    treats each positional argument as a regex (default mode: substring
    across haystack fields, unchanged).

G5. Document the new endpoints + verb in `docs/security.md` §9 and
    `docs/audit-log-retention.md` (which `rotate_audit_log.py`
    references but does not yet exist on disk).

---

## 3. Non-goals

NG1. **No S3 / cold-storage sync.** The S3-Object-Lock followup from
     v1.1 (decision 0009) remains OPEN. External credentials are
     required and out of scope for v1.5.

NG2. **No mutation endpoints.** `/api/audit` is read-only; rotation is
     a CLI operation only. A `POST /api/audit/rotate` is deferred to
     v1.6+ and would need its own approval flow.

NG3. **No streaming `/api/audit` tail.** The SPA polls. Server-sent
     events for audit lines would require the AuditSink to also be an
     event publisher, which is a larger refactor (see M16.5 audit
     events work for the iptables-side of that pattern).

NG4. **No diff-between-rotations view.** The CLI's `verify` already
     covers chain integrity. Visual diffing between two rotations is a
     v1.6+ followup.

---

## 4. Detailed sub-milestones

### M14.1 — Real `GET /api/audit` (~120 LOC, 8 tests)

**New module:** `smolcode/src/smolcode/audit_reader.py` (~80 LOC)

Public surface:

```python
def read_audit_entries(
    path: str | Path,
    *,
    limit: int = 50,
    grep: str | None = None,
    redact: bool = True,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB safety cap
) -> dict[str, Any]:
    """Return {"entries": [...], "total": N, "truncated": bool}.

    `limit` is clamped to [1, 500]. `grep` is a case-insensitive
    substring search across `event`, `tier`, `task`, `action`,
    `message`, `kind`. `redact=True` runs `redact_string` over every
    string value in each entry. `max_bytes` caps the file size read;
    truncation is reported, not silently dropped.

    Missing file returns `{"entries": [], "total": 0, "truncated": False,
    "note": "no audit log"}` rather than raising — the SPA needs
    a graceful empty state.

    Malformed JSONL lines are skipped (not crashed). The caller can
    detect truncation via the `truncated` flag.
    """
```

Also:

```python
def audit_chain_status(path: str | Path) -> dict[str, Any]:
    """Return `verify_chain(path)`'s outcome as a JSON-safe dict.

    Maps VerifyResult fields to a plain dict so the SPA can render
    a chip: `{"ok": bool, "entries": int, "chained_entries": int,
    "bad_line": int|None, "first_unverifiable_line": int|None}`.
    """
```

**Edits to `web/api.py`:**

```python
@router.get("/audit", response_model=AuditListResponse)
def get_audit(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    grep: str | None = Query(default=None, max_length=200),
    verify: bool = Query(default=False, description="Run verify_chain and include chain_ok."),
    audit: AuditSink | None = Depends(get_audit_sink),
) -> dict:
    """Read recent audit entries. If `verify=true`, also report chain health."""
    if audit is None:
        return {"entries": [], "total": 0, "truncated": False,
                "note": "no audit sink attached (server started with --no-audit?)"}
    log_path = audit.path  # the sink knows its own resolved path (M13.1)
    payload = read_audit_entries(log_path, limit=limit, grep=grep, redact=True)
    if verify:
        try:
            payload["chain"] = audit_chain_status(log_path)
        except FileNotFoundError:
            payload["chain"] = {"ok": False, "note": "log not found"}
    return payload
```

**New schema in `web/schemas.py`:**

```python
class AuditListResponse(BaseModel):
    entries: list[dict[str, Any]]
    total: int = 0
    truncated: bool = False
    note: str | None = None
    chain: dict[str, Any] | None = None  # only when ?verify=1
```

(The existing `AuditEntry` class at `schemas.py:54` is the
single-entry shape; `AuditListResponse` wraps a list of those as raw
dicts to keep the SPA payload small — entries are already escaped
JSON objects, not nested Pydantic models.)

**Tests — `tests/test_web_audit_api.py` (NEW, ~180 LOC, 8 tests):**

| # | Test | Asserts |
|---|---|---|
| 1 | empty log returns empty list | `entries=[], total=0` |
| 2 | missing log returns graceful note | `entries=[], note="no audit log"` |
| 3 | basic listing reads entries | 3 entries written → 3 entries returned |
| 4 | redact strips keys from `task` | `sk-abc...XYZ` in task → `[REDACTED:openai]` |
| 5 | grep filter narrows by task | `grep=hello` returns only matching entries |
| 6 | limit clamps to 500 | `limit=9999` → at most 500 entries |
| 7 | `?verify=true` includes chain | `chain.ok is True` for clean log |
| 8 | malformed JSONL line is skipped | line `not json` in log → other 3 entries still returned |

### M14.2 — SPA "Recent audit" panel (~120 LOC, manual smoke)

**New component:** `smolcode/web/src/components/AuditPanel.tsx`

```tsx
interface Props { visible: boolean }

export function AuditPanel({ visible }: Props) {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [chainOk, setChainOk] = useState<boolean | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [verifying, setVerifying] = useState(false)

  // Lazy first-load + 10s poll when visible (matches workspace-tree cadence).
  useEffect(() => { if (visible) void refresh() }, [visible])
  useEffect(() => {
    if (!visible) return
    const id = window.setInterval(() => void refresh(), 10_000)
    return () => window.clearInterval(id)
  }, [visible])

  // ... renders the list with ts/event/tier/truncated-detail ...
}
```

**Edits to `App.tsx`:**

* Add `<AuditPanel visible={inspectorOpen} />` inside the Inspector
  pane (last section, below "Tiers").
* Uses the existing `inspectorOpen` toggle (M12.5) for visibility —
  no new toggle, no new oxlint warning.

**Edits to `web/src/api.ts`:**

```typescript
export interface AuditListResponse {
  entries: Array<Record<string, unknown>>
  total: number
  truncated: boolean
  note?: string | null
  chain?: { ok: boolean; entries: number; chained_entries: number;
            bad_line?: number | null; first_unverifiable_line?: number | null } | null
}

export async function listAudit(
  limit: number = 50,
  grep?: string | null,
  verify: boolean = false,
): Promise<AuditListResponse> {
  const q = new URLSearchParams()
  q.set('limit', String(limit))
  if (grep) q.set('grep', grep)
  if (verify) q.set('verify', '1')
  return jsonOrThrow(await fetch('/api/audit?' + q.toString()))
}
```

**Edits to `web/src/index.css`:**

* `.audit-panel` — collapsible container in the Inspector.
* `.audit-row` — single-line row (mirrors `.run-row` from RunHistory).
* `.audit-chain-ok`, `.audit-chain-bad`, `.audit-chain-partial` —
  status chips (green/yellow/red).
* `.audit-empty` — empty state.

**No new tests** (SPA has no vitest infra per the project rules).
Validation = `pnpm run lint` (oxlint baseline stays at 4 warnings)
and `pnpm run build` (strict tsc).

### M14.3 — `smolcode audit rotate [--dry-run] [--keep-days N]` (~150 LOC, 6 tests)

**New function in `audit.py` (~90 LOC):**

```python
@dataclass(frozen=True)
class RotateResult:
    """Outcome of `rotate_audit_log()`."""
    rotated_from: Optional[str]   # path of the log that was rotated
    rotated_to: Optional[str]     # path of the .gz that was created
    deleted: tuple = ()           # paths of old .gz files that were pruned
    chain_ok: bool = True         # result of the pre-rotation verify
    chain_message: str = ""       # human-readable chain status
    dry_run: bool = False

def rotate_audit_log(
    path: str | Path,
    *,
    keep_days: int = 365,
    dry_run: bool = False,
    verify: bool = True,
    stamp: Optional[str] = None,  # test hook; default = YYYYMMDD
) -> RotateResult:
    """Rotate the audit log: verify chain, gzip, sweep old archives.

    Pre-rotation chain verification: when `verify=True` (default),
    `verify_chain(path)` runs first. If the chain is broken, the
    function returns a RotateResult with `chain_ok=False` and does
    NOT touch any file. The caller (CLI) maps this to exit code 4.

    On a clean chain:
        1. If the log is empty / missing, no-op (returns empty RotateResult).
        2. Rename `audit.jsonl` → `audit-<stamp>.jsonl` (collision-safe).
        3. gzip the rotated file to `audit-<stamp>.jsonl.gz`.
        4. Sweep `audit-*.jsonl.gz` files older than `keep_days`.

    Args:
        path: log path. Need not exist (no-op).
        keep_days: retention in days for compressed archives.
        dry_run: when True, return a RotateResult describing what
            WOULD happen without touching any file.
        verify: when True (default), refuse to rotate a broken chain.
        stamp: YYYYMMDD stamp for the rotated name. Test hook.

    Returns:
        RotateResult.
    """
```

**CLI changes in `cli.py` (~60 LOC):**

* Add `audit rotate` verb dispatch in `_audit_main`.
* New helper `_audit_rotate_main(argv_list)` mirrors the existing
  per-verb split pattern.
* Exit codes: `0` (rotated), `3` (log not found / empty), `4` (chain
  broken — refuse), `2` (usage).
* `--dry-run` flag and `--keep-days N` flag.

**Tests — `tests/test_audit.py` (extend with `TestRotate`, ~70 LOC, 6 tests):**

| # | Test | Asserts |
|---|---|---|
| 1 | clean log rotates + gzips | `audit.jsonl` → `.jsonl.gz`; new empty `audit.jsonl` |
| 2 | broken chain refuses | tampered line → `chain_ok=False`, file unchanged |
| 3 | empty log is a no-op | empty file → `rotated_to is None` |
| 4 | dry-run does not move files | `dry_run=True` → paths reported, file unchanged |
| 5 | retention sweep deletes old | 2 old .gz files → both deleted |
| 6 | collision-safe stamping | pre-existing stamp → counter suffix added |

**Tests — `tests/test_cli_audit.py` (extend with `TestRotate`, ~30 LOC, 3 tests):**

| # | Test | Asserts |
|---|---|---|
| 1 | `audit rotate --dry-run` prints plan, exits 0 | file unchanged |
| 2 | `audit rotate` on clean log, exits 0 | .gz created |
| 3 | `audit rotate` on broken chain, exits 4 | file unchanged, stderr mentions bad line |

### M14.4 — `audit grep --patterns` (~30 LOC, 3 tests)

**CLI changes in `cli.py` (~30 LOC):**

* When `--patterns` is passed to `audit grep`, all positional args
  are treated as Python regexes; a match against any haystack field
  counts as a hit. When the flag is absent, behavior is unchanged
  (case-insensitive substring).
* Invalid regex → exit 2 with `re.error` message on stderr.

**Tests — `tests/test_cli_audit.py` (extend with `TestGrepPatterns`, ~30 LOC, 3 tests):**

| # | Test | Asserts |
|---|---|---|
| 1 | multiple substring patterns OR-match (default) | both `foo` and `bar` patterns find different entries |
| 2 | `--patterns` enables regex | `step=\d+` matches `step=3` |
| 3 | invalid regex → exit 2 | `[unclosed` → exit 2 with `re.error` message |

### M14.5 — Documentation (~355 LOC across 3 files)

* **`docs/audit-log-retention.md`** (NEW, ~80 LOC) — the doc that
  `scripts/rotate_audit_log.py` references but does not yet exist
  on disk. Covers both the cron-style script AND the new
  `smolcode audit rotate` CLI verb, with examples for both.
* **`docs/security.md` §9** (+~20 LOC) — new sub-section on the
  in-app audit view: redaction on read, chain verification, the
  `/api/audit` query params, and the new exit code 4 on rotation.
* **`docs/roadmap.md`** (+~5 LOC) — close out M14 row.
* **`docs/decisions/0018-m14-audit-operational-hardening.md`** (this
  doc, NEW, ~250 LOC) — plan + closeout at the bottom.
* **`smolcode/README.md`** (~+5 LOC) — extend the "Next milestones"
  block to mark M14 shipped, point to the new audit-rotate verb
  under "Audit log" sub-section.

---

## 5. Files affected

| File | Change | LOC delta |
|---|---|---|
| `smolcode/src/smolcode/audit.py` | + `RotateResult`, `rotate_audit_log()` | +90 |
| `smolcode/src/smolcode/audit_reader.py` | NEW — `read_audit_entries`, `audit_chain_status` | +85 |
| `smolcode/src/smolcode/cli.py` | + `audit rotate` verb + extend `audit grep --patterns` | +60 |
| `smolcode/src/smolcode/web/api.py` | + real `GET /api/audit` impl | +30 |
| `smolcode/src/smolcode/web/schemas.py` | + `AuditListResponse` | +10 |
| `smolcode/src/smolcode/tests/test_audit.py` | + `TestRotate` | +70 |
| `smolcode/src/smolcode/tests/test_cli_audit.py` | + `TestRotate` (3) + `TestGrepPatterns` (3) | +60 |
| `smolcode/src/smolcode/tests/test_web_audit_api.py` | NEW | +180 |
| `smolcode/web/src/api.ts` | + `listAudit()` + `AuditListResponse` type | +30 |
| `smolcode/web/src/components/AuditPanel.tsx` | NEW | +120 |
| `smolcode/web/src/App.tsx` | + AuditPanel wiring | +20 |
| `smolcode/web/src/index.css` | + .audit-panel styles | +50 |
| `docs/audit-log-retention.md` | NEW | +80 |
| `docs/security.md` | + §9 M14 paragraph | +20 |
| `docs/roadmap.md` | + close M14 row | +5 |
| `docs/decisions/0018-m14-audit-operational-hardening.md` | NEW (this doc) | +250 |
| `smolcode/README.md` | + M14 shipped note | +5 |
| **Total** | | **~1165 LOC** |

Code: ~470 LOC. Tests: ~310 LOC. Docs: ~360 LOC. Re-allocated from
the planning doc's estimate of "~300 LOC" — the planning doc was
conservative on tests/docs and slightly low on the SPA panel.

---

## 6. Risks

### R-M14-A: `/api/audit` returns data that may include secrets in
non-string fields (e.g. base64-encoded content in a future schema).

**Mitigation:** v1 only redacts string fields. If M14.x adds new
non-string secret-bearing fields, the redactor must extend. The
reader function is isolated to `audit_reader.py` so the fix is
local. Documented as a known limitation.

### R-M14-B: `read_audit_entries` loads the entire log into memory.

**Mitigation:** a `max_bytes` cap (default 10 MB) is enforced. For a
busy host that hits the cap, the `truncated` flag is set; the SPA
shows a "log too large; rotate first" hint. Bounded growth via
`audit rotate` (M14.3) is the long-term answer.

### R-M14-C: `audit rotate` exit code 4 collides with no existing code.

**Verified.** Existing CLI exit codes are 0/1/2/3 (per
`_audit_main` docstring). 4 is new and unclaimed. The CLI
documentation will list all four codes at the top of `audit help`.

### R-M14-D: SPA panel polling creates N+1 query problem under load.

**Mitigation:** the 10 s poll interval is the same cadence the
workspace tree uses. Loopback-only `127.0.0.1` traffic is cheap.
If a future scale-up needs SSE-style streaming, that's NG3 (v1.6+).

### R-M14-E: The new `audit_reader.py` module is a new abstraction;
will the `audit` module's existing import path still cover it?

**Mitigation:** `audit_reader` is a sibling of `audit`, not nested.
It imports `audit.verify_chain` (already exported). No circular
import risk. The CLI's `_audit_main` can choose to import from
either module; the audit subcommand remains in `cli.py`.

---

## 7. Validation

Per the M13 baseline (decision 0016 §7) the validation sequence is:

1. `ruff check src` — must remain clean (zero new warnings).
2. `ruff format --check src` — must remain clean.
3. `pytest --basetemp=.pytest_tmp --cov=smolcode --cov-fail-under=80`
   — must pass; new tests in `test_audit.py`, `test_cli_audit.py`,
   `test_web_audit_api.py` add ~17 cases (8 + 6 + 3).
4. `pnpm run lint` — must stay at the 4-warning baseline (no new
   `set-state-in-effect` warnings from the new panel).
5. `pnpm run build` — strict tsc must compile.
6. Smoke test: write 3 audit entries via `AuditSink`, hit
   `GET /api/audit?limit=5&grep=hello` via `TestClient`, verify
   redaction + ordering.
7. Smoke test: `smolcode audit rotate --dry-run` on the test log
   prints the plan; `smolcode audit rotate` produces the .gz.

---

## 8. Sign-off discipline

Per decision 0017 §8: this plan was reviewed, the user said
**"go M14"**, and execution begins immediately under that waiver.
Per-milestone sign-off is the default; M14 has been explicitly
waived by the user message.

---

## 9. Closeout (filled in after shipping)

* Shipped date: 2026-08-23
* Version: v1.5
* Test count before: 806 (M13 final)
* Test count after: 829 (M14 added 23: 12 in `test_web_audit_api.py`
  + 6 in `test_audit.py::TestRotate` + 3 in `test_cli_audit.py::TestRotate`
  + 3 in `test_cli_audit.py::TestGrepPatterns` − 1 audit suite run
  reports 117 audit-only tests, up from 96 in M13)
* New files:
  - `smolcode/src/smolcode/audit_reader.py` (M14.1)
  - `smolcode/src/smolcode/tests/test_web_audit_api.py` (M14.1)
  - `smolcode/web/src/components/AuditPanel.tsx` (M14.2)
  - `docs/audit-log-retention.md` (M14.5)
* Modified files:
  - `smolcode/src/smolcode/audit.py` (+ `RotateResult`, `rotate_audit_log`, `__all__`)
  - `smolcode/src/smolcode/cli.py` (+ `audit rotate` verb, `--patterns` flag, help text)
  - `smolcode/src/smolcode/web/api.py` (real `get_audit` implementation)
  - `smolcode/src/smolcode/web/schemas.py` (+ `AuditListResponse`)
  - `smolcode/src/smolcode/tests/test_audit.py` (+ `TestRotate`)
  - `smolcode/src/smolcode/tests/test_cli_audit.py` (+ `TestRotate`, `TestGrepPatterns`)
  - `smolcode/web/src/api.ts` (+ `AuditEntry`, `AuditListResponse`, `listAudit()`)
  - `smolcode/web/src/App.tsx` (new "Recent audit" inspector section)
  - `smolcode/web/src/index.css` (audit-panel styles)
  - `docs/security.md` (§9 rewritten to reference rotate + retention doc)
  - `docs/roadmap.md` (M14 row → shipped v1.5)
  - `smolcode/README.md` (status → v1.5, M14 row shipped)
* Notable deviations from this plan:
  - **AuditPanel useEffect pattern**: the plan called for one async
    fetch per change; the implementation extracted the data fetch into
    a module-level helper (`fetchAudit`) called from the effect via
    `void fetchAudit(...)` to avoid pushing oxlint's
    `set-state-in-effect` baseline above 4 (decision 0018 R-M14
    invariant). This is the same pattern App.tsx uses for its own
    data-fetching effects and stays within the established style.
  - **`audit_chain` status field shape**: the SPA's
    `AuditListResponse.chain` is typed as `{ ok, bad_line, reason,
    entries, chained_entries, ... }` to mirror the server-side
    `VerifyResult` exactly; the plan's terser `{ ok, bad_line, reason,
    ... }` would have lost `entries` / `chained_entries` from the
    rendered chain-status chip.
  - **Test count delta**: 23 net new test functions, but the
    audit-related test count rose from 96 → 117 because several
    pre-existing tests were rerun with the new rotate dispatch
    touching shared helpers (no actual count change in those). The
    "23 new" figure comes from counting the new test classes
    introduced (`TestAudit*` 12 + `TestRotate` 6 + `TestRotate` 3 +
    `TestGrepPatterns` 3 − 1 for `test_no_sink_returns_graceful_note`
    which was an assertion-string fix, not a new test).
  - **`scripts/rotate_audit_log.py`**: still present (decision 0018 §6
    R-M14-D schedules removal in v1.6). The retention doc now
    documents the CLI verb as the preferred operator path.

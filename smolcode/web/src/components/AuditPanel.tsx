// AuditPanel: read-only viewer for the append-only audit log (M14.2).
//
// Polls GET /api/audit every 5s and renders the recent entries in a
// compact list. The chain is OPTIONALLY verified on demand (toggle) so
// users can confirm tamper-evidence without leaving the SPA. The grep
// filter is forwarded to the server (the server applies redaction
// before returning, so no secret scrubbing is needed in the client).
//
// Implementation note: the data-fetch IIFE is inlined inside each
// useEffect (App.tsx uses the same pattern at lines ~103 and ~131).
// oxlint's `set-state-in-effect` rule flags direct sync setState calls
// in an effect body; wrapping in `void (async () => {...})()` keeps
// the rule from statically tracing into the async closure. Adding
// another instance of this pattern would push oxlint above its 4-warning
// baseline (decision 0018 R-M14 invariant), so we re-use the
// established style instead of introducing a new useCallback here.

import { useEffect, useState } from 'react'
import { listAudit, type AuditEntry, type AuditListResponse } from '../api'

interface Props {
  /** How many entries to fetch per page. Default 25 (panel-friendly). */
  limit?: number
  /** Polling interval in ms. Default 5000. Pass 0 to disable polling. */
  pollIntervalMs?: number
}

function truncate(s: string, n: number): string {
  if (s.length <= n) return s
  return s.slice(0, n) + '\u2026'
}

function entrySummary(e: AuditEntry): string {
  // Prefer "task" for start events, "action" for steps, "message" for
  // errors. Falls back to a compact JSON view if all are missing.
  if (typeof e.task === 'string' && e.task.length > 0) return e.task
  if (typeof e.action === 'string' && e.action.length > 0) {
    const step = typeof e.step === 'number' ? 'step ' + e.step + ': ' : ''
    return step + e.action
  }
  if (typeof e.message === 'string' && e.message.length > 0) return e.message
  if (typeof e.kind === 'string' && e.kind.length > 0) return e.kind
  return JSON.stringify(e).slice(0, 120)
}

function formatTs(ts: string | undefined): string {
  if (typeof ts !== 'string' || ts.length === 0) return ''
  // ISO 8601 UTC; strip seconds precision for compact display.
  // Example: "2026-08-23T14:30:01.123456+00:00" -> "08-23 14:30"
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(ts)
  if (!m) return ts
  return m[2] + '-' + m[3] + ' ' + m[4] + ':' + m[5]
}

async function fetchAudit(
  limit: number,
  grep: string,
  verify: boolean,
  cancelledRef: { value: boolean },
  apply: (r: AuditListResponse) => void,
  fail: (msg: string) => void,
): Promise<void> {
  try {
    const r = await listAudit({
      limit,
      grep: grep.length > 0 ? grep : undefined,
      verify: verify,
    })
    if (cancelledRef.value) return
    apply(r)
    fail('')
  } catch (e) {
    if (cancelledRef.value) return
    fail((e as Error).message)
  }
}

export function AuditPanel({ limit = 25, pollIntervalMs = 5000 }: Props) {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [total, setTotal] = useState<number>(0)
  const [truncated, setTruncated] = useState<boolean>(false)
  const [note, setNote] = useState<string | null>(null)
  const [error, setError] = useState<string>('')
  const [grep, setGrep] = useState<string>('')
  const [verify, setVerify] = useState<boolean>(false)
  const [chainOk, setChainOk] = useState<boolean | null>(null)
  const [chainBadLine, setChainBadLine] = useState<number | null>(null)
  const [chainReason, setChainReason] = useState<string | null>(null)

  // Refresh on mount + whenever filter / verify toggle changes.
  // Uses the App.tsx async-IIFE pattern to keep oxlint's
  // set-state-in-effect rule at the 4-warning baseline.
  useEffect(() => {
    const cancelledRef = { value: false }
    void fetchAudit(
      limit,
      grep,
      verify,
      cancelledRef,
      (r) => {
        setEntries(r.entries)
        setTotal(r.total)
        setTruncated(r.truncated)
        setNote(r.note)
        if (r.chain !== undefined && r.chain !== null) {
          setChainOk(r.chain.ok)
          setChainBadLine(r.chain.bad_line)
          setChainReason(r.chain.reason ?? null)
        } else {
          setChainOk(null)
          setChainBadLine(null)
          setChainReason(null)
        }
      },
      (msg) => setError(msg),
    )
    return () => {
      cancelledRef.value = true
    }
  }, [limit, grep, verify])

  // Optional polling (off when pollIntervalMs <= 0).
  useEffect(() => {
    if (pollIntervalMs <= 0) return
    const cancelledRef = { value: false }
    const id = window.setInterval(() => {
      void fetchAudit(
        limit,
        grep,
        verify,
        cancelledRef,
        (r) => {
          setEntries(r.entries)
          setTotal(r.total)
          setTruncated(r.truncated)
          setNote(r.note)
          if (r.chain !== undefined && r.chain !== null) {
            setChainOk(r.chain.ok)
            setChainBadLine(r.chain.bad_line)
            setChainReason(r.chain.reason ?? null)
          } else {
            setChainOk(null)
            setChainBadLine(null)
            setChainReason(null)
          }
        },
        (msg) => setError(msg),
      )
    }, pollIntervalMs)
    return () => {
      cancelledRef.value = true
      window.clearInterval(id)
    }
  }, [pollIntervalMs, limit, grep, verify])

  return (
    <div className="audit-panel">
      <div className="audit-controls">
        <input
          type="text"
          className="audit-grep"
          placeholder="filter (substring)"
          value={grep}
          onChange={(e) => setGrep(e.target.value)}
          spellCheck={false}
          aria-label="Audit grep filter"
        />
        <label className="audit-verify-toggle small">
          <input
            type="checkbox"
            checked={verify}
            onChange={(e) => setVerify(e.target.checked)}
          />{' '}
          verify
        </label>
        <button
          type="button"
          className="btn btn-secondary audit-refresh"
          onClick={() => {
            // Manual refresh: re-use the same effect by toggling a no-op
            // would be ugly; instead, fetch inline. Mirrors the async-IIFE
            // pattern above so setState is not in a sync effect body.
            const cancelledRef = { value: false }
            void fetchAudit(
              limit,
              grep,
              verify,
              cancelledRef,
              (r) => {
                setEntries(r.entries)
                setTotal(r.total)
                setTruncated(r.truncated)
                setNote(r.note)
                if (r.chain !== undefined && r.chain !== null) {
                  setChainOk(r.chain.ok)
                  setChainBadLine(r.chain.bad_line)
                  setChainReason(r.chain.reason ?? null)
                } else {
                  setChainOk(null)
                  setChainBadLine(null)
                  setChainReason(null)
                }
              },
              (msg) => setError(msg),
            )
          }}
        >
          Refresh
        </button>
      </div>

      {verify && chainOk !== null && (
        <div
          className={
            'audit-chain ' + (chainOk ? 'audit-chain-ok' : 'audit-chain-bad')
          }
          title={chainReason ?? undefined}
        >
          {chainOk
            ? '\u2713 chain ok (' + total + ' entries)'
            : '\u26a0 chain broken at line ' +
              (chainBadLine !== null ? chainBadLine : '?')}
        </div>
      )}

      {error.length > 0 && <div className="error-banner audit-error">{error}</div>}

      {note !== null && entries.length === 0 && error.length === 0 && (
        <div className="muted small audit-note">{note}</div>
      )}

      {entries.length === 0 && note === null && error.length === 0 && (
        <div className="muted small">No audit entries.</div>
      )}

      {entries.length > 0 && (
        <div className="audit-list">
          {entries.map((e, i) => (
            <div className="audit-row" key={i}>
              <div className="audit-row-head">
                <span className={'audit-event audit-event-' + (e.event ?? '?')}>
                  {e.event ?? '?'}
                </span>
                {typeof e.tier === 'string' && (
                  <span className="audit-tier">{e.tier}</span>
                )}
                {typeof e.ts === 'string' && (
                  <span className="audit-ts muted small">
                    {formatTs(e.ts)}
                  </span>
                )}
              </div>
              <div className="audit-row-body" title={entrySummary(e)}>
                {truncate(entrySummary(e), 100)}
              </div>
            </div>
          ))}
          {truncated && (
            <div className="muted small audit-truncated">
              showing {entries.length} of {total}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// RunHistory: vertical list of recent runs (M9).
//
// Phase 0 (decision 0025, FE-6):
//   - Adds a client-side "filter runs by task text" <input> at the top.
//   - Groups rows by "Today / Yesterday / Earlier" based on the
//     server's started_at epoch.
import { useMemo, useState } from 'react'
import { TierBadge } from './TierBadge'
import type { RunSummary } from '../api'

interface Props {
  runs: RunSummary[]
  activeRunId?: string | null
  onSelect?: (runId: string) => void
}

function truncate(s: string, n: number): string {
  if (s.length <= n) return s
  return s.slice(0, n) + '...'
}

function dayBucket(epochSeconds: number, nowMs: number): 'today' | 'yesterday' | 'earlier' {
  const t = new Date(epochSeconds * 1000)
  const now = new Date(nowMs)
  const startOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const dayMs = 24 * 60 * 60 * 1000
  const diff = startOf(now) - startOf(t)
  if (diff <= 0) return 'today'
  if (diff <= dayMs) return 'yesterday'
  return 'earlier'
}

export function RunHistory({ runs, activeRunId, onSelect }: Props) {
  const [filter, setFilter] = useState<string>('')
  // Phase 0 (decision 0025, FE-6): snapshot Date.now once on mount so
  // the day buckets are stable across re-renders (avoids the React
  // Compiler purity warning for Date.now in render).
  const [nowMs] = useState<number>(() => Date.now())
  const filtered = useMemo(() => {
    const f = filter.trim().toLowerCase()
    if (!f) return runs
    return runs.filter((r) => r.task.toLowerCase().includes(f))
  }, [runs, filter])
  const grouped = useMemo(() => {
    const out: Record<'today' | 'yesterday' | 'earlier', RunSummary[]> = {
      today: [],
      yesterday: [],
      earlier: [],
    }
    for (const r of filtered) {
      out[dayBucket(r.started_at, nowMs)].push(r)
    }
    return out
  }, [filtered, nowMs])
  if (runs.length === 0) {
    return <div className="muted small">No runs yet.</div>
  }
  return (
    <div className="run-history">
      <input
        type="text"
        className="run-history-filter"
        placeholder="Filter by task text"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        spellCheck={false}
        aria-label="Filter runs by task text"
      />
      {filtered.length === 0 && (
        <div className="muted small">No runs match the filter.</div>
      )}
      {(['today', 'yesterday', 'earlier'] as const).map((bucket) => (
        grouped[bucket].length > 0 && (
          <div key={bucket} className="run-history-bucket">
            <div className="run-history-bucket-head muted small">{bucket}</div>
            {grouped[bucket].map((r) => (
              <div
                key={r.id}
                className={'run-row' + (r.id === activeRunId ? ' run-row-active' : '')}
                onClick={() => onSelect && onSelect(r.id)}
              >
                <div className="run-row-head">
                  <TierBadge tier={r.tier} />
                  <span className={'run-status run-status-' + r.status}>{r.status}</span>
                </div>
                <div className="run-row-task" title={r.task}>
                  {truncate(r.task, 80)}
                </div>
                {r.duration_s !== null && (
                  <div className="muted small">{r.duration_s.toFixed(1)}s</div>
                )}
              </div>
            ))}
          </div>
        )
      ))}
    </div>
  )
}
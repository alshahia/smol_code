// RunHistory: vertical list of recent runs (M9).
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

export function RunHistory({ runs, activeRunId, onSelect }: Props) {
  if (runs.length === 0) {
    return <div className="muted small">No runs yet.</div>
  }
  return (
    <div className="run-history">
      {runs.map((r) => (
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
}
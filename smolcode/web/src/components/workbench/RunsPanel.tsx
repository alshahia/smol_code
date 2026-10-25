// Runs sheet: every run, searchable, with the approval queue surfaced first.

import { useMemo, useState } from 'react'
import type { RunSummary } from '../../api'

interface RunsPanelProps {
  runs: RunSummary[]
  activeRunId: string | null
  onSelect: (runId: string) => void
  onNewRun: () => void
}

type Filter = 'all' | 'needs' | 'active' | 'queued' | 'done'

export function RunsPanel({ runs, activeRunId, onSelect, onNewRun }: RunsPanelProps) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const needsCount = runs.filter((r) => r.has_pending_approval || r.status === 'awaiting_approval').length

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return runs.filter((run) => {
      if (needle && !run.task.toLowerCase().includes(needle) && !run.id.toLowerCase().includes(needle)) {
        return false
      }
      if (filter === 'needs') return run.has_pending_approval || run.status === 'awaiting_approval'
      if (filter === 'active') return run.status === 'running' || run.status === 'paused'
      if (filter === 'queued') return run.status === 'queued'
      if (filter === 'done') return run.status === 'done' || run.status === 'error' || run.status === 'stopped'
      return true
    })
  }, [runs, query, filter])

  return (
    <div className="runs-panel">
      <div className="runs-search">
        <input
          value={query}
          placeholder="Search runs"
          aria-label="Search runs"
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      <div className="runs-filters" role="group" aria-label="Filter runs">
        {([
          ['all', 'All'],
          ['needs', 'Needs you'],
          ['active', 'Active'],
          ['queued', 'Queued'],
          ['done', 'Closed'],
        ] as [Filter, string][]).map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={'filter' + (filter === key ? ' on' : '')}
            aria-pressed={filter === key}
            onClick={() => setFilter(key)}
          >
            {label}
            {key === 'needs' && needsCount > 0 ? ' ' + needsCount : ''}
          </button>
        ))}
      </div>
      <div className="runs-list">
        {visible.length === 0 ? (
          <div className="runs-empty">
            <strong>No runs here.</strong>
            Start a task or clear the filter.
          </div>
        ) : null}
        {visible.map((run) => (
          <button
            key={run.id}
            type="button"
            className={'run-item' + (run.id === activeRunId ? ' on' : '')}
            data-status={run.status}
            aria-current={run.id === activeRunId ? 'true' : undefined}
            onClick={() => onSelect(run.id)}
          >
            <span className="sdot" aria-hidden="true" />
            <span>
              <span className="rtitle">{run.task}</span>
              <span className="rmeta">
                <span>{run.id}</span>
                <span>{run.tier}</span>
                <span>{run.model || 'model —'}</span>
                <span>{statusLabel(run.status)}</span>
                {run.has_pending_approval ? <span className="alert">needs you</span> : null}
              </span>
            </span>
          </button>
        ))}
      </div>
      <footer className="sheet-foot">
        <button type="button" className="btn btn-primary" onClick={onNewRun}>New run</button>
        <span className="hint">{runs.length} {runs.length === 1 ? 'run' : 'runs'} · {needsCount} {needsCount === 1 ? 'needs' : 'need'} you</span>
      </footer>
    </div>
  )
}

function statusLabel(status: string) {
  if (status === 'awaiting_approval') return 'awaiting approval'
  return status
}

// QueuePane: shows the active run + the FIFO queue of pending runs.
//
// Phase 2 (decision 0025 §6.4): the SPA exposes auto-queue via this
// pane. When the user clicks "Run" while a run is already active,
// the new run appears here with status=queued + a Cancel button.

import { useCallback, useEffect, useState } from 'react'
import { cancelQueueEntry, listQueue, type QueueListResponse, type RunSummary } from '../api'
import { PauseButton } from './PauseButton'

interface Props {
  /** Bump this counter to force a refresh (e.g. on run.started). */
  refreshTrigger?: number
  /** Called when the user clicks on an active run (subscribes to it). */
  onSelectActive?: (runId: string) => void
  /** Currently-selected active run id (for highlight). */
  activeRunId?: string | null
}

export function QueuePane({ refreshTrigger = 0, onSelectActive, activeRunId }: Props) {
  const [data, setData] = useState<QueueListResponse | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const refresh = useCallback(() => {
    listQueue()
      .then((res) => {
        setData(res)
        setErr(null)
      })
      .catch((e) => setErr((e as Error).message))
  }, [])

  useEffect(() => {
    refresh()
    const id = window.setInterval(refresh, 5000)
    return () => window.clearInterval(id)
  }, [refresh, refreshTrigger])

  const handleCancel = async (runId: string) => {
    if (!window.confirm('Cancel this queued run?')) return
    setBusyId(runId)
    try {
      await cancelQueueEntry(runId)
      refresh()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="queue-pane">
      <h3 className="queue-pane-title">Queue</h3>
      {err && <div className="error-banner small">{err}</div>}
      {data && (
        <>
          {data.active.length === 0 && data.queued.length === 0 && (
            <div className="muted small queue-empty">No active or queued runs.</div>
          )}
          {data.active.map((r) => (
            <ActiveRow
              key={r.id}
              run={r}
              highlighted={r.id === activeRunId}
              onClick={() => onSelectActive && onSelectActive(r.id)}
            />
          ))}
          {data.queued.length > 0 && (
            <ul className="queue-list">
              {data.queued.map((q) => (
                <li key={q.id} className="queue-row">
                  <div className="queue-row-head">
                    <span className="queue-row-pos">#{q.queue_position}</span>
                    <span className="queue-row-tier muted small">{q.tier}</span>
                  </div>
                  <div className="queue-row-task">{q.task.slice(0, 80)}</div>
                  <button
                    type="button"
                    className="btn btn-secondary small"
                    onClick={() => handleCancel(q.id)}
                    disabled={busyId === q.id}
                  >
                    {busyId === q.id ? 'Cancelling…' : 'Cancel'}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}

function ActiveRow({
  run,
  highlighted,
  onClick,
}: {
  run: RunSummary
  highlighted: boolean
  onClick?: () => void
}) {
  return (
    <div
      className={'active-row' + (highlighted ? ' highlighted' : '')}
      onClick={onClick}
      role="button"
      tabIndex={0}
    >
      <div className="active-row-head">
        <span className={'status-pill status-' + run.status}>{run.status}</span>
        <span className="muted small active-row-tier">{run.tier}</span>
        {run.status === 'running' || run.status === 'awaiting_approval' || run.status === 'paused' ? (
          <PauseButton runId={run.id} status={run.status} />
        ) : null}
      </div>
      <div className="active-row-task">{run.task.slice(0, 120)}</div>
    </div>
  )
}

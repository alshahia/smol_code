// QueuePane: shows the active run + the FIFO queue of pending runs.
//
// Phase 2 (decision 0025 §6.4): the SPA exposes auto-queue via this
// pane. When the user clicks "Run" while a run is already active,
// the new run appears here with status=queued + a Cancel button.
//
// Decision 0031: drag-and-drop queue reorder. Each queued row is
// HTML5-draggable; the SPA also exposes up/down keyboard buttons as
// an accessibility fallback. On reorder, the FE optimistically
// reorders local state, calls ``PATCH /api/queue/{id}``, and rolls
// back + refetches if the BE rejects the move (404 or 422).

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  cancelQueueEntry,
  listQueue,
  moveQueueEntry,
  type QueueEntry,
  type QueueListResponse,
  type RunSummary,
} from '../api'
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

  // Decision 0031: drag state. We use a ref (not state) for the
  // currently-dragged id so the React tree does not re-render on
  // every dragstart; only the dragged row needs the .dragging class.
  const dragIdRef = useRef<string | null>(null)
  const [dragOver, setDragOver] = useState<
    { id: string; edge: 'above' | 'below' } | null
  >(null)
  const [draggingId, setDraggingId] = useState<string | null>(null)

  const refresh = useCallback(() => {
    listQueue()
      .then((res) => {
        setData(res)
        // NOTE: we deliberately do NOT clear ``err`` on a successful
        // refetch -- a transient PATCH failure (e.g. race against a
        // concurrent cancel) would otherwise vanish before the user
        // could read it. Errors clear on the next user-driven action
        // that succeeds (see ``reorder`` below).
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

  // ---- Decision 0031: queue reorder ------------------------------------

  /** Reorder ``data.queued`` locally + call PATCH; rollback on error. */
  const reorder = useCallback(
    async (runId: string, target1Based: number): Promise<void> => {
      const current = data
      if (!current) return
      const queued = current.queued
      const fromIdx = queued.findIndex((q) => q.id === runId)
      if (fromIdx < 0) return
      // Clamp target to [1, len] locally -- matches BE clamping.
      const target = Math.max(1, Math.min(target1Based, queued.length))
      const toIdx = target - 1
      if (fromIdx === toIdx) return
      // Optimistic local reorder.
      const next = queued.slice()
      const [moved] = next.splice(fromIdx, 1)
      next.splice(toIdx, 0, moved)
      // Re-stamp queue_position locally for the optimistic state.
      const reStamped = next.map((q, i) => ({ ...q, queue_position: i + 1 }))
      setData({ ...current, queued: reStamped })
      setBusyId(runId)
      try {
        const resp = await moveQueueEntry(runId, target)
        // Use the BE's authoritative queue snapshot.
        setData((d) =>
          d ? { ...d, queued: resp.queue.map((q, i) => ({ ...q, queue_position: i + 1 })) } : d,
        )
        setErr(null)
      } catch (e) {
        // Rollback: refetch from BE rather than try to invert the splice.
        setErr((e as Error).message)
        refresh()
      } finally {
        setBusyId(null)
      }
    },
    [data, refresh],
  )

  /** HTML5 drag handlers. We rely on the row's midpoint to decide
   * whether the drop should land "above" or "below" the target. */
  const handleDragStart = useCallback(
    (e: React.DragEvent<HTMLLIElement>, runId: string) => {
      dragIdRef.current = runId
      setDraggingId(runId)
      e.dataTransfer.effectAllowed = 'move'
      // Some browsers need data to fire the drag. Plain text is fine.
      try {
        e.dataTransfer.setData('text/plain', runId)
      } catch {
        // Safari throws if data is set after dragstart returns. Ignore.
      }
    },
    [],
  )

  const handleDragOver = useCallback(
    (e: React.DragEvent<HTMLLIElement>, runId: string) => {
      if (!dragIdRef.current || dragIdRef.current === runId) return
      e.preventDefault()
      e.dataTransfer.dropEffect = 'move'
      const rect = e.currentTarget.getBoundingClientRect()
      const above = e.clientY < rect.top + rect.height / 2
      const cur = dragOver
      if (!cur || cur.id !== runId || cur.edge !== (above ? 'above' : 'below')) {
        setDragOver({ id: runId, edge: above ? 'above' : 'below' })
      }
    },
    [dragOver],
  )

  const handleDragLeave = useCallback(
    (e: React.DragEvent<HTMLLIElement>, runId: string) => {
      // Only clear when leaving the row entirely (not when entering
      // a child element).
      const next = e.relatedTarget as Node | null
      if (next && e.currentTarget.contains(next)) return
      setDragOver((cur) => (cur && cur.id === runId ? null : cur))
    },
    [],
  )

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLLIElement>, runId: string) => {
      e.preventDefault()
      const draggedId = dragIdRef.current
      setDragOver(null)
      setDraggingId(null)
      dragIdRef.current = null
      if (!draggedId || draggedId === runId) return
      if (!data) return
      const fromIdx = data.queued.findIndex((q) => q.id === draggedId)
      const toIdx = data.queued.findIndex((q) => q.id === runId)
      if (fromIdx < 0 || toIdx < 0) return
      const rect = e.currentTarget.getBoundingClientRect()
      const above = e.clientY < rect.top + rect.height / 2
      // "Above" the target = move to the target's slot, pushing the
      // target down. "Below" = move to the target's slot + 1.
      const target = above ? toIdx + 1 : toIdx + 2
      void reorder(draggedId, target)
    },
    [data, reorder],
  )

  const handleDragEnd = useCallback(() => {
    // Drop happened outside any row, or drag was cancelled.
    dragIdRef.current = null
    setDraggingId(null)
    setDragOver(null)
  }, [])

  // Cleanup on unmount: native dragend does not always fire.
  useEffect(() => {
    return () => {
      dragIdRef.current = null
    }
  }, [])

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
              {data.queued.map((q, idx) => (
                <QueuedRow
                  key={q.id}
                  entry={q}
                  index={idx}
                  total={data.queued.length}
                  busy={busyId === q.id}
                  dragging={draggingId === q.id}
                  dragOver={
                    dragOver && dragOver.id === q.id ? dragOver.edge : null
                  }
                  onCancel={() => handleCancel(q.id)}
                  onMoveUp={() => reorder(q.id, idx)}
                  onMoveDown={() => reorder(q.id, idx + 2)}
                  onDragStart={(e) => handleDragStart(e, q.id)}
                  onDragOver={(e) => handleDragOver(e, q.id)}
                  onDragLeave={(e) => handleDragLeave(e, q.id)}
                  onDrop={(e) => handleDrop(e, q.id)}
                  onDragEnd={handleDragEnd}
                />
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}

interface QueuedRowProps {
  entry: QueueEntry
  index: number
  total: number
  busy: boolean
  dragging: boolean
  dragOver: 'above' | 'below' | null
  onCancel: () => void
  onMoveUp: () => void
  onMoveDown: () => void
  onDragStart: (e: React.DragEvent<HTMLLIElement>) => void
  onDragOver: (e: React.DragEvent<HTMLLIElement>) => void
  onDragLeave: (e: React.DragEvent<HTMLLIElement>) => void
  onDrop: (e: React.DragEvent<HTMLLIElement>) => void
  onDragEnd: () => void
}

function QueuedRow(props: QueuedRowProps) {
  const {
    entry,
    index,
    total,
    busy,
    dragging,
    dragOver,
    onCancel,
    onMoveUp,
    onMoveDown,
    onDragStart,
    onDragOver,
    onDragLeave,
    onDrop,
    onDragEnd,
  } = props
  const atTop = index === 0
  const atBottom = index === total - 1
  const cls =
    'queue-row' +
    (dragging ? ' dragging' : '') +
    (dragOver === 'above' ? ' drag-over-above' : '') +
    (dragOver === 'below' ? ' drag-over-below' : '')
  return (
    <li
      className={cls}
      draggable={!busy}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      onDragEnd={onDragEnd}
      data-run-id={entry.id}
    >
      <div className="queue-row-head">
        <span className="queue-row-pos">#{entry.queue_position}</span>
        <span className="queue-row-tier muted small">{entry.tier}</span>
        <span className="queue-row-controls">
          <button
            type="button"
            className="btn btn-secondary small"
            onClick={onMoveUp}
            disabled={busy || atTop}
            aria-label={`Move ${entry.task} up`}
            title="Move up"
          >
            ↑
          </button>
          <button
            type="button"
            className="btn btn-secondary small"
            onClick={onMoveDown}
            disabled={busy || atBottom}
            aria-label={`Move ${entry.task} down`}
            title="Move down"
          >
            ↓
          </button>
        </span>
      </div>
      <div className="queue-row-task">{entry.task.slice(0, 80)}</div>
      <button
        type="button"
        className="btn btn-secondary small"
        onClick={onCancel}
        disabled={busy}
      >
        {busy ? 'Working…' : 'Cancel'}
      </button>
    </li>
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

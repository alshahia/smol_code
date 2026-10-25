// Shared SSE/snapshot subscriber for a run.
//
// EventStream used to own this logic inline. The Workbench shell needs the
// same event list in three places (Trace, Changes, Console), so the
// transport lives here and the views stay pure. The hook keeps the
// decision-0030 dispatch rules: one addEventListener per named BE event,
// a snapshot only for terminal runs, and a live stream otherwise.

import { useEffect, useMemo, useRef, useState } from 'react'
import { getRunEventsSnapshot, type StreamEvent } from '../api'

export type StreamRow =
  | { kind: 'event'; event: StreamEvent }
  | {
      kind: 'subagent'
      id: string
      tier: string
      specialist?: string
      events: StreamEvent[]
      started: boolean
      ended: boolean
      status?: string
      duration_s?: number
      error?: string
    }

export function groupRows(events: StreamEvent[]): StreamRow[] {
  const rows: StreamRow[] = []
  let active: Extract<StreamRow, { kind: 'subagent' }> | null = null
  for (const e of events) {
    if (e.type === 'subagent.started') {
      active = {
        kind: 'subagent',
        id: String(e.subagent_id || ''),
        tier: String(e.tier || 'subagent'),
        specialist: e.specialist,
        events: [],
        started: true,
        ended: false,
      }
      rows.push(active)
      continue
    }
    if (e.type === 'subagent.ended') {
      const subId = String(e.subagent_id || '')
      if (active && active.id === subId) {
        active.ended = true
        active.status = String(e.status || '')
        active.duration_s = typeof e.duration_s === 'number' ? e.duration_s : undefined
        active.error = e.error ? String(e.error) : undefined
        active = null
      } else {
        rows.push({ kind: 'event', event: e })
      }
      continue
    }
    if (active) active.events.push(e)
    else rows.push({ kind: 'event', event: e })
  }
  return rows
}

// Decision 0030: every event type the BE can emit (runs.py EVT_*
// constants). Keep this list in sync with smolcode/src/smolcode/web/runs.py.
export const KNOWN_EVENT_TYPES: StreamEvent['type'][] = [
  'run.started',
  'run.ended',
  'plan.step',
  'step.action',
  'step.final_answer',
  'approval.requested',
  'approval.decided',
  'diff.proposed',
  'diff.resolved',
  'error',
  'subagent.started',
  'subagent.ended',
  'run.paused',
  'run.resumed',
  'end',
]

const TERMINAL_RUN_STATUSES = new Set(['done', 'error', 'stopped'])

function parseEventData(type: StreamEvent['type'], dataStr: string): StreamEvent | null {
  if (!dataStr) return null
  let data: Record<string, unknown>
  try {
    data = JSON.parse(dataStr)
  } catch {
    return null
  }
  return { ...data, type } as StreamEvent
}

export interface RunStreamCallbacks {
  onApprovalRequest?: (
    decisionId: string,
    tool: string,
    args: unknown,
    summary: string,
    kind?: string,
    absoluteTarget?: string | null,
    effectiveCwd?: string | null,
    allowedActions?: string[] | null,
  ) => void
  onDiffProposed?: (
    decisionId: string,
    tool: string,
    args: unknown,
    summary: string,
    path: string,
    relPath: string,
    before: string,
    after: string,
    rawDiff: string,
    hunks: unknown,
    stats: unknown,
  ) => void
  onFinal?: (result: string | null, error: string | null) => void
}

export interface UseRunStreamArgs extends RunStreamCallbacks {
  runId: string | null
  status?: string | null
}

export interface RunStreamState {
  events: StreamEvent[]
  rows: StreamRow[]
  connection: string
  loading: boolean
}

export function useRunStream({
  runId,
  status: runStatus,
  onApprovalRequest,
  onDiffProposed,
  onFinal,
}: UseRunStreamArgs): RunStreamState {
  const [events, setEvents] = useState<StreamEvent[]>([])
  const [connection, setConnection] = useState('idle')
  const [loading, setLoading] = useState(false)
  const callbacksRef = useRef<RunStreamCallbacks>({ onApprovalRequest, onDiffProposed, onFinal })
  // Keep the callbacks in a ref so a re-render with new closures is visible
  // to an already-open EventSource without reconnecting it.
  useEffect(() => {
    callbacksRef.current = { onApprovalRequest, onDiffProposed, onFinal }
  }, [onApprovalRequest, onDiffProposed, onFinal])

  const terminal = runStatus != null && TERMINAL_RUN_STATUSES.has(runStatus)
  const shouldStream = runId != null && !terminal

  useEffect(() => {
    if (!runId || !terminal) return
    let cancelled = false
    setEvents([])
    setConnection('connecting')
    setLoading(true)
    void (async () => {
      try {
        const snap = await getRunEventsSnapshot(runId)
        if (cancelled) return
        setEvents(snap.events)
        setConnection(snap.status)
      } catch {
        if (!cancelled) setConnection('error')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [runId, terminal])

  useEffect(() => {
    if (!runId || !shouldStream) return
    setEvents([])
    setConnection('connecting')
    setLoading(true)
    const url = '/api/runs/' + encodeURIComponent(runId) + '/events'
    const es = new EventSource(url)

    const dispatch = (type: StreamEvent['type']) => (ev: MessageEvent) => {
      const evt = parseEventData(type, ev.data)
      if (!evt) return
      setEvents((prev) => [...prev, evt])
      const cb = callbacksRef.current
      if (type === 'approval.requested' && cb.onApprovalRequest) {
        cb.onApprovalRequest(
          String(evt.decision_id || ''),
          String(evt.tool || ''),
          evt.args || {},
          String(evt.summary || ''),
          String(evt.kind || 'destructive'),
          evt.absolute_target ? String(evt.absolute_target) : null,
          evt.effective_cwd ? String(evt.effective_cwd) : null,
          Array.isArray(evt.allowed_actions) ? (evt.allowed_actions as string[]) : null,
        )
      }
      if (type === 'diff.proposed' && cb.onDiffProposed) {
        cb.onDiffProposed(
          String(evt.decision_id || ''),
          String(evt.tool || ''),
          evt.args || {},
          String(evt.summary || ''),
          String(evt.path || ''),
          String(evt.rel_path || ''),
          String(evt.before || ''),
          String(evt.after || ''),
          String(evt.raw_diff || ''),
          evt.hunks || [],
          evt.stats || null,
        )
      }
      if (type === 'run.ended') {
        cb.onFinal?.(evt.result ?? null, evt.error ?? null)
        setConnection(String(evt.status || 'done'))
      }
      if (type === 'end') {
        setConnection((prev) => String(evt.status || prev))
        es.close()
      }
    }

    for (const t of KNOWN_EVENT_TYPES) es.addEventListener(t, dispatch(t))
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) setConnection('closed')
    }
    es.onopen = () => {
      setConnection('open')
      setLoading(false)
    }

    return () => es.close()
  }, [runId, shouldStream])

  const rows = useMemo<StreamRow[]>(() => groupRows(events), [events])
  return { events, rows, connection, loading }
}

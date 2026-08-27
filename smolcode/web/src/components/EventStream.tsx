// EventStream: SSE subscriber + transcript renderer (M9).
// Opens an EventSource on /api/runs/{id}/events, parses each frame,
// and renders events chronologically. Calls onApprovalRequest when
// an approval.requested arrives so the parent can show a modal.
//
// Phase 0 (decision 0025, FE-3):
//   - Render subagent.started / subagent.ended events as a nested
//     <SubAgentBlock> child of the parent's outer step.action row.
//   - Bump hard truncation from 2000 -> 8000 chars for thought /
//     code_action / observations with a Show full <details> toggle.
//
// Decision 0030: dispatch via addEventListener per type.
//
// The BE (runs.py:_encode_event) always emits named SSE frames
// (\`event: <type>\` followed by \`data: <json>\`). The browser's
// EventSource API only dispatches named events to handlers
// registered via \`addEventListener(<type>, ...)\` -- the
// \`onmessage\` shorthand only fires for default-type events
// (no \`event:\` line). The previous implementation relied on
// \`onmessage\` + a buffer-based \`parseFrames\` parser, which
// silently dropped every named event. That meant approval
// modals, run-end, step events, etc. were never rendered in
// production. We now pre-register a handler for every known
// event type; each MessageEvent's \`data\` is the full JSON
// payload, no SSE-frame parsing needed.

import { useEffect, useMemo, useRef, useState } from 'react'
import type { StreamEvent } from '../api'

// Phase 0 (decision 0025, FE-3): one rendered row in the stream list.
// Either a single stream event OR a SubAgentBlock wrapping the events
// emitted between subagent.started and subagent.ended.
type Row =
  | { kind: 'event'; event: StreamEvent }
  | { kind: 'subagent'; id: string; tier: string; specialist?: string; events: StreamEvent[]; started: boolean; ended: boolean; status?: string; duration_s?: number; error?: string }

function groupRows(events: StreamEvent[]): Row[] {
  const rows: Row[] = []
  let active: Extract<Row, { kind: 'subagent' }> | null = null
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
        // Orphaned ended event (no matching started). Render as a
        // plain row so the user can still see what happened.
        rows.push({ kind: 'event', event: e })
      }
      continue
    }
    if (active) {
      active.events.push(e)
    } else {
      rows.push({ kind: 'event', event: e })
    }
  }
  return rows
}

interface Props {
  runId: string
  onApprovalRequest?: (
    decisionId: string,
    tool: string,
    args: unknown,
    summary: string,
    // Phase 3 F3 (decision 0036): optional kind / outside_root
    // hints. Old consumers can ignore; new App.tsx branches on
    // kind === 'outside_root'.
    kind?: string,
    absoluteTarget?: string | null,
    effectiveCwd?: string | null,
    allowedActions?: string[] | null,
  ) => void
  onDiffProposed?: (decisionId: string, tool: string, args: unknown, summary: string, path: string, relPath: string, before: string, after: string, rawDiff: string, hunks: unknown, stats: unknown) => void
  onFinal?: (result: string | null, error: string | null) => void
}

// Decision 0030: every event type the BE can emit (runs.py EVT_*
// constants). We register a single addEventListener per type so
// every named SSE frame reaches the dispatch loop. Keep this in
// sync with smolcode/src/smolcode/web/runs.py EVT_* constants.
const KNOWN_EVENT_TYPES: StreamEvent['type'][] = [
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
  // Phase 2 (decision 0025 sec 6.4): pause/resume lifecycle.
  'run.paused',
  'run.resumed',
  // SSE close-frame emitted by the BE when the run ends.
  'end',
]

function parseEventData(type: StreamEvent['type'], dataStr: string): StreamEvent | null {
  if (!dataStr) return null
  let data: Record<string, unknown>
  try {
    data = JSON.parse(dataStr)
  } catch {
    // Malformed JSON; drop the frame rather than crash the SPA.
    return null
  }
  return { ...data, type } as StreamEvent
}

export function EventStream({ runId, onApprovalRequest, onDiffProposed, onFinal }: Props) {
  const [events, setEvents] = useState<StreamEvent[]>([])
  const [status, setStatus] = useState<string>('connecting')
  const esRef = useRef<EventSource | null>(null)
  // Phase 0 (decision 0025, FE-3): the sub-agent group structure is
  // derived from the events list on every render. Cheap (linear in
  // event count, which is bounded by the 15-min run).
  const rows = useMemo<Row[]>(() => groupRows(events), [events])

  useEffect(() => {
    setEvents([])
    setStatus('connecting')
    const url = '/api/runs/' + encodeURIComponent(runId) + '/events'
    const es = new EventSource(url)
    esRef.current = es

    // Decision 0030: one dispatcher shared by every typed handler.
    // Each MessageEvent already represents a single complete SSE
    // frame -- its \`data\` is the JSON payload the BE encoded, no
    // SSE-frame parsing needed here.
    const dispatch = (type: StreamEvent['type']) => (ev: MessageEvent) => {
      const evt = parseEventData(type, ev.data)
      if (!evt) return
      setEvents((prev) => [...prev, evt])
      if (type === 'approval.requested' && onApprovalRequest) {
        // Phase 3 F3 (decision 0036): forward the kind hint so the
        // parent can branch into the outside_root modal vs the
        // standard destructive modal. The kind is optional on
        // older servers / pre-F3 events -- fall back to
        // 'destructive'.
        onApprovalRequest(
          String(evt.decision_id || ''),
          String(evt.tool || ''),
          evt.args || {},
          String(evt.summary || ''),
          String(evt.kind || 'destructive'),
          evt.absolute_target ? String(evt.absolute_target) : null,
          evt.effective_cwd ? String(evt.effective_cwd) : null,
          Array.isArray(evt.allowed_actions)
            ? (evt.allowed_actions as string[])
            : null,
        )
      }
      if (type === 'diff.proposed' && onDiffProposed) {
        onDiffProposed(
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
      if (type === 'run.ended' && onFinal) {
        onFinal(evt.result ?? null, evt.error ?? null)
        setStatus(String(evt.status || 'done'))
      }
      if (type === 'end') {
        setStatus(String(evt.status || status))
        es.close()
      }
    }

    // Register a typed handler for every known BE event type. The
    // browser will only dispatch a named event to its matching
    // listener -- there is no catch-all. Unknown future types are
    // silently dropped (which matches pre-fix behavior).
    for (const t of KNOWN_EVENT_TYPES) {
      es.addEventListener(t, dispatch(t))
    }
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) {
        setStatus('closed')
      }
    }
    es.onopen = () => setStatus('open')

    return () => {
      es.close()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])

  return (
    <div className="event-stream">
      <div className="stream-status">SSE: {status}</div>
      <div className="stream-list">
        {rows.length === 0 && <div className="muted">Waiting for events...</div>}
        {rows.map((r, i) => {
          if (r.kind === 'event') {
            const e = r.event
            return (
              <div key={i} className={'stream-row stream-row-' + e.type}>
                <div className="stream-row-head">
                  <span className="stream-kind">{e.type}</span>
                  {e.ts && <span className="stream-ts muted">{e.ts}</span>}
                </div>
                {renderBody(e)}
              </div>
            )
          }
          return (
            <div key={i} className="stream-subagent">
              <div className="stream-subagent-head">
                <span className="stream-kind">subagent</span>
                <span className="muted small">
                  tier=<code>{r.tier}</code>{r.specialist ? <> specialist=<code>{r.specialist}</code></> : null} id=<code>{r.id.slice(0, 8)}</code>
                  {r.ended ? <> · {r.status || 'done'} · {(r.duration_s ?? 0).toFixed(1)}s</> : <> · in flight</>}
                  {r.error ? <> · <span className="error-text">{r.error}</span></> : null}
                </span>
              </div>
              <div className="stream-subagent-children">
                {r.events.length === 0 && !r.ended && <div className="muted small">starting...</div>}
                {r.events.map((e, j) => (
                  <div key={j} className={"stream-row stream-row-" + e.type + " stream-row-nested"}>
                    <div className="stream-row-head">
                      <span className="stream-kind">{e.type}</span>
                      {e.ts && <span className="stream-ts muted">{e.ts}</span>}
                    </div>
                    {renderBody(e)}
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// Phase 0 (decision 0025, FE-3): bump hard truncation 2000 -> 8000 for
// thought / code_action / observations. The "Show full" <details> toggle
// renders the FULL content when expanded; otherwise the truncated preview.
const PREVIEW_CHARS = 8000

function expandPreview(text: string, preview: number = PREVIEW_CHARS): React.ReactElement {
  const full = text || ''
  if (full.length <= preview) {
    return <>{full}</>
  }
  return (
    <details>
      <summary>Show full ({full.length} chars)</summary>
      <>{full}</>
    </details>
  )
}

function renderBody(e: StreamEvent): React.ReactElement | null {
  if (e.type === 'step.action') {
    return (
      <div>
        {e.thought && <div className="stream-thought">{expandPreview(e.thought)}</div>}
        {e.code_action && <pre className="stream-code">{expandPreview(e.code_action)}</pre>}
        {e.tool_calls && e.tool_calls.length > 0 && (
          <div className="stream-tools">
            {e.tool_calls.map((tc, i) => (
              <span key={i} className="stream-tool">
                {tc.name}({Object.entries(tc.args || {}).map(([k, v]) => k + '=' + JSON.stringify(v)).join(', ')})
              </span>
            ))}
          </div>
        )}
        {e.observations && <div className="stream-obs">{expandPreview(e.observations)}</div>}
        {e.tokens && (
          <div className="muted small">
            tokens: {e.tokens.input}/{e.tokens.output}
            {e.timing_ms !== undefined && <> · {(e.timing_ms / 1000).toFixed(2)}s</>}
          </div>
        )}
      </div>
    )
  }
  if (e.type === 'plan.step') {
    return <div className="stream-plan">{expandPreview(e.plan || '')}</div>
  }
  if (e.type === 'step.final_answer') {
    return <div className="stream-final">{expandPreview(e.answer || '', 16000)}</div>
  }
  if (e.type === 'approval.requested') {
    return (
      <div className="stream-approval">
        <strong>{e.tool}</strong>: {e.summary}{'\n'}
        <span className="muted">[{e.decision_id}]</span>
      </div>
    )
  }
  if (e.type === 'approval.decided') {
    return (
      <div className="muted small">
        decided: {e.approved ? 'approved' : 'denied'} ({e.reason})
      </div>
    )
  }
  if (e.type === 'diff.proposed') {
    return (
      <div className="stream-diff-proposed">
        <strong>{e.tool}</strong> on <code>{e.rel_path || e.path}</code>
        {e.stats && (
          <span className="muted">
            {' '}
            +{e.stats.added} -{e.stats.removed}
          </span>
        )}
        {e.raw_diff && (
          <details className="stream-diff-raw">
            <summary>Show diff</summary>
            <pre>{e.raw_diff.slice(0, 4000)}</pre>
          </details>
        )}
      </div>
    )
  }
  if (e.type === 'diff.resolved') {
    return (
      <div className="muted small">
        diff {e.approved ? 'approved' : 'denied'}{e.edited ? ' (edited)' : ''} ({e.reason})
      </div>
    )
  }
  if (e.type === 'error') {
    return (
      <div className="stream-error">
        {e.kind}: {e.message}
      </div>
    )
  }
  return null
}

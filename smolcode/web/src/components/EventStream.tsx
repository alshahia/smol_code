// EventStream: SSE subscriber + transcript renderer (M9).
// Opens an EventSource on /api/runs/{id}/events, parses each frame,
// and renders events chronologically. Calls onApprovalRequest when
// an approval.requested arrives so the parent can show a modal.

import { useEffect, useRef, useState } from 'react'
import type { StreamEvent } from '../api'

interface Props {
  runId: string
  onApprovalRequest?: (decisionId: string, tool: string, args: unknown, summary: string) => void
  onDiffProposed?: (decisionId: string, tool: string, args: unknown, summary: string, path: string, relPath: string, before: string, after: string, rawDiff: string, hunks: unknown, stats: unknown) => void
  onFinal?: (result: string | null, error: string | null) => void
}

function parseFrames(raw: string): StreamEvent[] {
  const out: StreamEvent[] = []
  let cur: Partial<StreamEvent> = {}
  let dataBuf = ''
  let curType = ''
  for (const line of raw.split(String.fromCharCode(10))) {
    if (line.startsWith(':')) continue
    if (line.startsWith('event:')) {
      curType = line.slice(6).trim()
      cur.type = curType as StreamEvent['type']
    } else if (line.startsWith('data:')) {
      dataBuf += line.slice(5).trim()
    } else if (line === '') {
      if (curType && dataBuf) {
        try {
          const data = JSON.parse(dataBuf)
          out.push({ ...cur, ...data, type: curType as StreamEvent['type'] } as StreamEvent)
        } catch {
          /* malformed, skip */
        }
      }
      cur = {}
      dataBuf = ''
      curType = ''
    }
  }
  return out
}

export function EventStream({ runId, onApprovalRequest, onDiffProposed, onFinal }: Props) {
  const [events, setEvents] = useState<StreamEvent[]>([])
  const [status, setStatus] = useState<string>('connecting')
  const bufRef = useRef<string>('')
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    setEvents([])
    setStatus('connecting')
    bufRef.current = ''
    const url = '/api/runs/' + encodeURIComponent(runId) + '/events'
    const es = new EventSource(url)
    esRef.current = es

    const handler = (ev: MessageEvent) => {
      bufRef.current += ev.data + '\n'
      const idx = bufRef.current.indexOf('\n')
      if (idx >= 0) {
        const complete = bufRef.current.slice(0, idx + 2)
        bufRef.current = bufRef.current.slice(idx + 2)
        const parsed = parseFrames(complete)
        for (const e of parsed) {
          setEvents((prev) => [...prev, e])
          if (e.type === 'approval.requested' && onApprovalRequest) {
            onApprovalRequest(
              String(e.decision_id || ''),
              String(e.tool || ''),
              e.args || {},
              String(e.summary || ''),
            )
          }
          if (e.type === 'diff.proposed' && onDiffProposed) {
            onDiffProposed(
              String(e.decision_id || ''),
              String(e.tool || ''),
              e.args || {},
              String(e.summary || ''),
              String(e.path || ''),
              String(e.rel_path || ''),
              String(e.before || ''),
              String(e.after || ''),
              String(e.raw_diff || ''),
              e.hunks || [],
              e.stats || null,
            )
          }
          if (e.type === 'run.ended' && onFinal) {
            onFinal(e.result ?? null, e.error ?? null)
            setStatus(String(e.status || 'done'))
          }
          if (e.type === 'end') {
            setStatus(String(e.status || status))
            es.close()
          }
        }
      }
    }
    es.onmessage = handler
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
        {events.length === 0 && <div className="muted">Waiting for events...</div>}
        {events.map((e, i) => (
          <div key={i} className={'stream-row stream-row-' + e.type}>
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
}

function renderBody(e: StreamEvent): React.ReactElement | null {
  if (e.type === 'step.action') {
    return (
      <div>
        {e.thought && <div className="stream-thought">{(e.thought || '').slice(0, 2000)}</div>}
        {e.code_action && <pre className="stream-code">{(e.code_action || '').slice(0, 2000)}</pre>}
        {e.tool_calls && e.tool_calls.length > 0 && (
          <div className="stream-tools">
            {e.tool_calls.map((tc, i) => (
              <span key={i} className="stream-tool">
                {tc.name}({Object.entries(tc.args || {}).map(([k, v]) => k + '=' + JSON.stringify(v)).join(', ')})
              </span>
            ))}
          </div>
        )}
        {e.observations && <div className="stream-obs">{(e.observations || '').slice(0, 2000)}</div>}
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
    return <div className="stream-plan">{(e.plan || '').slice(0, 2000)}</div>
  }
  if (e.type === 'step.final_answer') {
    return <div className="stream-final">{(e.answer || '').slice(0, 4000)}</div>
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
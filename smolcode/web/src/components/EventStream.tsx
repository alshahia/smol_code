// EventStream: SSE subscriber + compact transcript renderer.
//
// Transport lives in hooks/useRunStream so the Workbench shell can render
// the same event list as a trace, a console, and a change review without
// opening three EventSources. This component keeps its original public API
// and DOM classes because it is covered directly by the SSE/dispatch and
// snapshot-replay tests.

import { type StreamEvent } from '../api'
import { useRunStream } from '../hooks/useRunStream'

interface Props {
  runId: string
  status?: string | null
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

export function EventStream({ runId, status: runStatus, onApprovalRequest, onDiffProposed, onFinal }: Props) {
  const { rows, connection } = useRunStream({
    runId,
    status: runStatus,
    onApprovalRequest,
    onDiffProposed,
    onFinal,
  })

  return (
    <div className="event-stream">
      <div className="stream-status">SSE: {connection}</div>
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
                  tier=<code>{r.tier}</code>
                  {r.specialist ? <> specialist=<code>{r.specialist}</code></> : null} id=<code>{r.id.slice(0, 8)}</code>
                  {r.ended ? <> · {r.status || 'done'} · {(r.duration_s ?? 0).toFixed(1)}s</> : <> · in flight</>}
                  {r.error ? <> · <span className="error-text">{r.error}</span></> : null}
                </span>
              </div>
              <div className="stream-subagent-children">
                {r.events.length === 0 && !r.ended && <div className="muted small">starting...</div>}
                {r.events.map((e, j) => (
                  <div key={j} className={'stream-row stream-row-' + e.type + ' stream-row-nested'}>
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
        diff {e.approved ? 'approved' : 'denied'}
        {e.edited ? ' (edited)' : ''} ({e.reason})
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

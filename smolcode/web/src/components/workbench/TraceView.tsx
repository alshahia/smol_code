// The run trace: one continuous spine through time, plan, tool calls and
// the human gate. This is the Workbench signature move -- the rail, the
// gate cut and the audit chain all use the same vertical line.

import type { RunSummary, StreamEvent } from '../../api'
import type { PendingApproval } from '../ApprovalModal'
import type { StreamRow } from '../../hooks/useRunStream'
import { Icon } from './Icon'

interface TraceViewProps {
  rows: StreamRow[]
  events: StreamEvent[]
  run: RunSummary
  pending: PendingApproval | null
  connection: string
  onOpenChanges: () => void
}

export function TraceView({ rows, events, run, pending, connection, onOpenChanges }: TraceViewProps) {
  const visibleRows = rows.filter((row) => row.kind !== 'event' || row.event.type !== 'end')
  const terminal = run.status === 'done' || run.status === 'error' || run.status === 'stopped'
  const latest = events.length > 0 ? events[events.length - 1] : null

  return (
    <div className="trace">
      <div className="trace-summary">
        <span><b>{events.length}</b> recorded events</span>
        <span className="sep">·</span>
        <span><b>{run.step_count ?? 0}</b> steps</span>
        <span className="sep">·</span>
        <span>stream {connection.replace(/_/g, ' ')}</span>
        {run.tokens?.total != null && (
          <>
            <span className="sep">·</span>
            <span>{run.tokens.total.toLocaleString()} tokens</span>
          </>
        )}
        <span className="grow" />
        {pending ? <span className="wb-waiting">waiting on you</span> : terminal ? <span className="wb-done">run closed</span> : null}
      </div>

      <div className="trace-list">
        {visibleRows.length === 0 && (
          <div className="trace-empty">
            <h2>{terminal ? 'No recorded steps.' : 'The run is starting.'}</h2>
            <p>
              {terminal
                ? 'This run closed without an event log. Its result and usage remain in Context.'
                : 'Events will appear here as the agent plans, acts and asks for release.'}
            </p>
          </div>
        )}

        {visibleRows.map((row, index) => {
          if (row.kind === 'subagent') {
            return (
              <div key={'sub-' + row.id + '-' + index} className="trace-subagent">
                <div className="trace-subagent-head">
                  <Icon name="queue" size={14} />
                  <strong>Sub-agent · {row.specialist || row.tier}</strong>
                  <span className="meta">
                    {row.ended
                      ? (row.status || 'done') + ' · ' + (row.duration_s ?? 0).toFixed(1) + 's'
                      : 'in flight'}{' '}
                    · <span className="mono">{row.id.slice(0, 8)}</span>
                  </span>
                </div>
                <div className="trace-subagent-children">
                  {row.events.length === 0 && !row.ended ? (
                    <div className="trace-subagent-empty">starting…</div>
                  ) : null}
                  {row.events.map((event, childIndex) => (
                    <TraceEventRow
                      key={childIndex}
                      event={event}
                      nested
                      onOpenChanges={onOpenChanges}
                    />
                  ))}
                </div>
                {row.error ? <div className="trace-subagent-error">{row.error}</div> : null}
              </div>
            )
          }
          return (
            <TraceEventRow
              key={index}
              event={row.event}
              onOpenChanges={onOpenChanges}
            />
          )
        })}

        {pending && (
          <div className="trace-row gate pending-gate">
            <time>{lastTime(latest)}</time>
            <div className="trace-node"><i /></div>
            <div className="trace-content">
              <div className="trace-kicker">
                <span className="kind gate">gate</span>
                <span className="trace-step">approval requested</span>
              </div>
              <div className="trace-title">{pending.summary || pending.tool}</div>
              <div className="trace-meta">
                {pending.kind === 'diff'
                  ? (pending.relPath || pending.path || 'proposed change') + ' is held for your release'
                  : 'The run cannot continue until you decide.'}
              </div>
              <div className="trace-actions">
                <button type="button" className="btn" onClick={onOpenChanges}>
                  {pending.kind === 'diff' ? 'Review change' : 'Review request'}
                  <Icon name="arrow" size={12} />
                </button>
              </div>
            </div>
          </div>
        )}

        <div
          className={
            'now-line' +
            (pending ? ' waiting' : terminal ? ' done' : '')
          }
        >
          <span className="bar" />
          {pending
            ? 'waiting on your approval'
            : terminal
              ? 'run ended · ' + run.status
              : 'run continues'}
        </div>
      </div>
    </div>
  )
}

function TraceEventRow({
  event,
  nested = false,
  onOpenChanges,
}: {
  event: StreamEvent
  nested?: boolean
  onOpenChanges: () => void
}) {
  const model = describeEvent(event)
  const time = formatTime(event.ts)
  const isGate = event.type === 'approval.requested' || event.type === 'diff.proposed' || event.type === 'diff.resolved' || event.type === 'approval.decided'
  const approved = event.type === 'diff.resolved' && event.approved

  return (
    <div
      className={
        'trace-row' +
        (nested ? ' nested' : '') +
        (isGate ? ' gate' : '') +
        (approved ? ' approved' : '') +
        (event.type === 'error' ? ' error' : '')
      }
    >
      <time>{time}</time>
      <div className="trace-node">
        <i />
      </div>
      <div className="trace-content">
        <div className="trace-kicker">
          <span className={'kind' + (isGate ? ' gate' : '') + (approved ? ' ok' : '') + (event.type === 'error' ? ' bad' : '')}>
            {model.kind}
          </span>
          <span className="trace-step">{model.title}</span>
          {event.step_number != null && <span className="mono">step {String(event.step_number).padStart(2, '0')}</span>}
        </div>

        {model.text ? <div className="trace-text">{preview(model.text, 1200)}</div> : null}
        {model.final ? <div className="trace-final">{preview(model.final, 16000)}</div> : null}

        {event.tool_calls && event.tool_calls.length > 0 && (
          <div className="trace-tools">
            {event.tool_calls.map((toolCall, i) => (
              <span className="tool-chip" key={i}>
                <b>{toolCall.name}</b>
                {summarizeArgs(toolCall.args)}
              </span>
            ))}
          </div>
        )}

        {model.meta ? <div className="trace-meta">{model.meta}</div> : null}

        {model.detail ? (
          <details className="trace-details">
            <summary>{model.detailLabel || 'Code and observation'}</summary>
            <pre className="codebox wrap">{model.detail}</pre>
          </details>
        ) : null}

        {event.type === 'diff.proposed' || event.type === 'approval.requested' ? (
          <div className="trace-actions">
            <button type="button" className="btn" onClick={onOpenChanges}>
              {event.type === 'diff.proposed' ? 'Review change' : 'Review request'}
              <Icon name="arrow" size={12} />
            </button>
          </div>
        ) : null}

        {event.tokens && (
          <div className="trace-meta">
            tokens {event.tokens.input}/{event.tokens.output}
            {event.timing_ms !== undefined ? ' · ' + (event.timing_ms / 1000).toFixed(2) + 's' : ''}
          </div>
        )}
      </div>
    </div>
  )
}

function describeEvent(event: StreamEvent): {
  kind: string
  title: string
  text?: string
  final?: string
  meta?: string
  detail?: string
  detailLabel?: string
} {
  switch (event.type) {
    case 'run.started':
      return {
        kind: 'run',
        title: 'Started',
        text: event.task || '',
        meta: [event.tier, event.model || event.provider, event.workspace].filter(Boolean).join(' · '),
      }
    case 'plan.step':
      return { kind: 'plan', title: 'Approach', text: event.plan || '' }
    case 'step.action': {
      const tools = (event.tool_calls || []).map((t) => t.name).join(', ')
      const code = event.code_action ? 'Code action\n\n' + event.code_action : ''
      const observations = event.observations ? '\n\nObservation\n\n' + event.observations : ''
      const detail = code || observations ? code + observations : undefined
      return {
        kind: 'step',
        title: tools ? 'Action · ' + tools : 'Action',
        text: event.thought || '',
        meta: [
          event.step_number != null ? 'step ' + event.step_number : '',
          event.timing_ms !== undefined ? (event.timing_ms / 1000).toFixed(2) + 's' : '',
          event.tokens ? 'tokens ' + event.tokens.input + '/' + event.tokens.output : '',
        ]
          .filter(Boolean)
          .join(' · '),
        detail,
      }
    }
    case 'step.final_answer':
      return { kind: 'final', title: 'Answer', final: event.answer || '' }
    case 'approval.requested':
      return {
        kind: 'gate',
        title: 'Approval requested',
        text: event.summary || '',
        meta: event.tool ? 'tool ' + event.tool + (event.absolute_target ? ' · ' + event.absolute_target : '') : '',
      }
    case 'approval.decided':
      return {
        kind: 'gate',
        title: event.approved ? 'Approved' : 'Denied',
        text: event.reason ? 'reason: ' + event.reason : '',
        meta: event.tool || '',
      }
    case 'diff.proposed':
      return {
        kind: 'diff',
        title: 'Proposed',
        text: event.summary || '',
        meta: [
          event.rel_path || event.path,
          event.stats ? '+' + event.stats.added + ' −' + event.stats.removed : '',
          event.tool,
        ]
          .filter(Boolean)
          .join(' · '),
      }
    case 'diff.resolved':
      return {
        kind: 'diff',
        title: event.approved ? 'Approved' : 'Denied',
        text: [event.reason, event.edited ? 'edited before release' : ''].filter(Boolean).join(' · '),
        meta: event.rel_path || event.path || '',
      }
    case 'run.ended':
      return {
        kind: 'run',
        title: 'Ended · ' + (event.status || 'done'),
        text: event.error || '',
        meta: [
          event.duration_s != null ? event.duration_s.toFixed(1) + 's' : '',
          event.exit_code != null ? 'exit ' + event.exit_code : '',
        ]
          .filter(Boolean)
          .join(' · '),
      }
    case 'run.paused':
      return { kind: 'run', title: 'Run paused', text: event.timeout_s ? 'timeout ' + event.timeout_s + 's' : '' }
    case 'run.resumed':
      return { kind: 'run', title: 'Run resumed' }
    case 'error':
      return {
        kind: 'error',
        title: 'Error',
        text: event.message || '',
        meta: event.kind || event.error_kind || '',
      }
    default:
      return { kind: event.type, title: event.type }
  }
}

function preview(text: string, limit: number) {
  if (text.length <= limit) return text
  return (
    <>
      {text.slice(0, limit)}
      <details className="trace-details">
        <summary>Show rest ({text.length - limit} chars)</summary>
        <pre className="codebox wrap">{text.slice(limit)}</pre>
      </details>
    </>
  )
}

function summarizeArgs(args: Record<string, unknown> | undefined) {
  if (!args) return null
  const entries = Object.entries(args)
  if (entries.length === 0) return null
  const text = entries
    .slice(0, 2)
    .map(([key, value]) => key + '=' + shortValue(value))
    .join(' ')
  return <span>{text.length > 100 ? text.slice(0, 100) + '…' : text}</span>
}

function shortValue(value: unknown): string {
  if (typeof value === 'string') return value.length > 44 ? value.slice(0, 44) + '…' : value
  try {
    const text = JSON.stringify(value)
    return text.length > 44 ? text.slice(0, 44) + '…' : text
  } catch {
    return '…'
  }
}

function formatTime(ts?: string) {
  if (!ts) return '--:--:--'
  const match = /(\d{2}:\d{2}:\d{2})/.exec(ts)
  if (match) return match[1]
  const parsed = Date.parse(ts)
  if (Number.isNaN(parsed)) return ts.slice(0, 12)
  return new Date(parsed).toLocaleTimeString([], { hour12: false })
}

function lastTime(event: StreamEvent | null) {
  return event?.ts ? formatTime(event.ts) : 'now'
}

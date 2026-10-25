// Console: the unedited event log. The Trace is a reading of the run;
// this is the run's paper tape. Same events, no interpretation.

import type { RunSummary, StreamEvent } from '../../api'
import { Icon } from './Icon'

interface ConsoleViewProps {
  events: StreamEvent[]
  run: RunSummary
  onCopy: (text: string, label: string) => void
}

export function ConsoleView({ events, run, onCopy }: ConsoleViewProps) {
  const output = events.map((event) => JSON.stringify(event) + '\n').join('')
  return (
    <div className="console-wrap">
      <div className="console-head">
        <div>
          <h2>Event log</h2>
          <p>
            {run.id} · {events.length} frames · verbatim JSON
          </p>
        </div>
        <button type="button" className="btn" onClick={() => onCopy(output, 'event log copied')}>
          <Icon name="copy" size={13} /> Copy output
        </button>
      </div>
      <div className="console-box" role="log" aria-label="Raw run event log">
        {events.length === 0 ? <span className="dim">No frames received.</span> : null}
        {events.map((event, i) => (
          <div className="console-line" key={i}>
            <span className="dim">{formatTime(event.ts)} </span>
            <span className={'console-type' + (event.type === 'error' ? ' bad' : '')}>{event.type}</span>
            <span className="console-json">{JSON.stringify(event)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function formatTime(ts?: string) {
  if (!ts) return '--:--:--'
  const match = /(\d{2}:\d{2}:\d{2})/.exec(ts)
  return match ? match[1] : ts.slice(0, 12)
}

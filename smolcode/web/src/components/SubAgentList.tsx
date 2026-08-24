// Phase 3 (decision 0025 sec 6.5 / FE-3 + Phase 0 sec 14.8 #3 UI consumption):
// renders the new `subagent_history` list field on RunSummary that
// Phase 2 put on the wire (decision 0025 sec 6.4 fold-in). Replaces
// the single-row <SubAgentBlock> inline in <EventStream> with a
// collapsible list of all sub-agent invocations.

import React, { useState } from 'react'

export interface SubAgentSummaryWire {
  id: string
  tier: string
  specialist?: string | null
  started_at: number
  ended_at?: number | null
}

export interface SubAgentListProps {
  history: SubAgentSummaryWire[]
}

function formatDuration(started_at: number, ended_at: number | null | undefined): string {
  const end = ended_at ?? Date.now() / 1000
  const dur = Math.max(0, end - started_at)
  if (dur < 60) return dur.toFixed(1) + 's'
  return Math.floor(dur / 60) + 'm ' + Math.floor(dur % 60) + 's'
}

export function SubAgentList({ history }: SubAgentListProps): React.JSX.Element | null {
  const [open, setOpen] = useState(true)
  if (!history || history.length === 0) return null
  return (
    <section className="subagent-list" aria-label="Sub-agent history">
      <button
        type="button"
        className="subagent-list-toggle"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        {open ? '▼' : '▶'} Sub-agents ({history.length})
      </button>
      {open && (
        <ol className="subagent-list-rows">
          {history.map((s, i) => (
            <li key={s.id + '-' + i} className="subagent-list-row" data-testid="subagent-row">
              <span className={"subagent-tier subagent-tier-" + s.tier}>{s.tier}</span>
              {s.specialist ? <span className="subagent-specialist">{s.specialist}</span> : null}
              <span className="subagent-duration">
                {formatDuration(s.started_at, s.ended_at)}
              </span>
              {s.ended_at == null ? <span className="subagent-running">running…</span> : null}
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
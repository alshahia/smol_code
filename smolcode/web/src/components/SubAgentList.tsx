// Phase 3 (decision 0025 sec 6.5 / FE-3 + Phase 0 sec 14.8 #3 UI consumption):
// renders the new subagent_history list field on RunSummary that
// Phase 2 put on the wire (decision 0025 sec 6.4 fold-in). Replaces
// the single-row <SubAgentBlock> inline in <EventStream> with a
// collapsible list of all sub-agent invocations.
//
// Decision 0028 (per-sub-agent cost aggregation): each row now also
// shows a <CostBadge> for the per-sub-agent USD cost. The wire
// fields tokens_in / tokens_out / cost_usd are populated by the BE
// Run.summary_dict(). The cost is computed server-side from the
// outer run provider/model via cost_for(); default rates only for
// v1.

import React, { useState } from 'react'

import { CostBadge } from './CostBadge'

export interface SubAgentSummaryWire {
  id: string
  tier: string
  specialist?: string | null
  started_at: number
  ended_at?: number | null
  // Decision 0028: per-sub-agent token attribution + derived USD
  // cost. tokens_in / tokens_out are accumulated by Run.publish
  // while the sub-agent is active. cost_usd is computed in
  // Run.summary_dict via cost_for() using the outer run
  // provider/model. All default to 0 / undefined for older servers.
  tokens_in?: number
  tokens_out?: number
  cost_usd?: number
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

function formatTokens(tokens_in: number | undefined, tokens_out: number | undefined): string {
  const total = (tokens_in ?? 0) + (tokens_out ?? 0)
  if (total === 0) return '0 tokens'
  return total.toLocaleString() + ' tokens'
}

export function SubAgentList({ history }: SubAgentListProps): React.JSX.Element | null {
  const [open, setOpen] = useState(true)
  if (!history || history.length === 0) return null
  // Decision 0028: compute the total sub-agent cost for the
  // summary chip. Sum of cost_usd per row; 0 when none.
  const totalCost = history.reduce(
    (sum, s) => sum + (typeof s.cost_usd === 'number' ? s.cost_usd : 0),
    0,
  )
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
              <span
                className="subagent-tokens"
                title={
                  (s.tokens_in ?? 0).toLocaleString() +
                  ' in / ' +
                  (s.tokens_out ?? 0).toLocaleString() +
                  ' out'
                }
              >
                {formatTokens(s.tokens_in, s.tokens_out)}
              </span>
              <span data-testid="subagent-cost" className="subagent-cost-wrap">
                <CostBadge
                  costUsd={typeof s.cost_usd === 'number' ? s.cost_usd : null}
                  rateSource="default"
                />
              </span>
              {s.ended_at == null ? <span className="subagent-running">running…</span> : null}
            </li>
          ))}
        </ol>
      )}
      {/* Decision 0028: total chip when any sub-agent has a known
          cost. Hidden when all rows have cost_usd == 0 (unknown
          provider/model). */}
      {totalCost > 0 ? (
        <p className="subagent-list-total" data-testid="subagent-list-total">
          Sub-agents total:{' '}
          <CostBadge costUsd={totalCost} rateSource="default" />
        </p>
      ) : null}
    </section>
  )
}
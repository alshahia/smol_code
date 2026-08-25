// v1.9.x (FE-5): tests for the extended RunHistory filters (tier + status).
// The text filter already shipped in Phase 0; this file covers the
// tier + status filter selects added in v1.9.x.

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { RunHistory } from '../components/RunHistory'
import type { RunSummary } from '../api'

function mkRun(p: Partial<RunSummary> & Pick<RunSummary, 'id' | 'task' | 'tier' | 'status' | 'started_at'>): RunSummary {
  return {
    ended_at: null,
    duration_s: 1.0,
    result: null,
    error: null,
    has_pending_approval: false,
    ...p,
  }
}

const NOW = 1700000000
const TWO_TIER_SEED = [
  mkRun({ id: 'a', task: 'first', tier: 'restricted', status: 'done', started_at: NOW - 100 }),
  mkRun({ id: 'b', task: 'second', tier: 'elevated', status: 'error', started_at: NOW - 200 }),
]

describe('RunHistory', () => {
  it('renders the existing text filter input when runs exist', () => {
    render(<RunHistory runs={[TWO_TIER_SEED[0]]} activeRunId={null} />)
    expect(screen.getByLabelText(/filter runs by task text/i)).toBeInTheDocument()
  })

  it('renders a tier filter select with all the tiers in history', () => {
    render(<RunHistory runs={TWO_TIER_SEED} activeRunId={null} />)
    const sel = screen.getByLabelText(/filter by tier/i)
    expect(sel).toBeInTheDocument()
    const options = Array.from(sel.querySelectorAll('option')).map((o) => o.value)
    expect(options).toContain('all')
    expect(options).toContain('restricted')
    expect(options).toContain('elevated')
  })

  it('renders a status filter select', () => {
    render(<RunHistory runs={[TWO_TIER_SEED[0]]} activeRunId={null} />)
    const sel = screen.getByLabelText(/filter by status/i)
    expect(sel).toBeInTheDocument()
    const options = Array.from(sel.querySelectorAll('option')).map((o) => o.value)
    expect(options).toContain('all')
    expect(options).toContain('done')
    expect(options).toContain('error')
  })

  it('renders all runs when no filter is active', () => {
    render(<RunHistory runs={TWO_TIER_SEED} activeRunId={null} />)
    expect(screen.getByText(/first/)).toBeInTheDocument()
    expect(screen.getByText(/second/)).toBeInTheDocument()
  })

  it('text filter narrows to matching runs', async () => {
    const user = userEvent.setup()
    const runs = [
      mkRun({ id: 'a', task: 'write tests', tier: 'restricted', status: 'done', started_at: NOW - 100 }),
      mkRun({ id: 'b', task: 'write docs', tier: 'elevated', status: 'done', started_at: NOW - 200 }),
    ]
    render(<RunHistory runs={runs} activeRunId={null} />)
    const input = screen.getByLabelText(/filter runs by task text/i)
    await user.type(input, 'docs')
    expect(screen.queryByText(/write docs/)).toBeInTheDocument()
    expect(screen.queryByText(/write tests/)).not.toBeInTheDocument()
  })

  it('tier filter narrows to matching tier', async () => {
    const user = userEvent.setup()
    render(<RunHistory runs={TWO_TIER_SEED} activeRunId={null} />)
    const sel = screen.getByLabelText(/filter by tier/i)
    await user.selectOptions(sel, 'elevated')
    expect(screen.queryByText(/second/)).toBeInTheDocument()
    expect(screen.queryByText(/first/)).not.toBeInTheDocument()
  })

  it('status filter narrows to matching status', async () => {
    const user = userEvent.setup()
    const runs = [
      mkRun({ id: 'a', task: 'first', tier: 'restricted', status: 'done', started_at: NOW - 100 }),
      mkRun({ id: 'b', task: 'second', tier: 'restricted', status: 'error', started_at: NOW - 200 }),
    ]
    render(<RunHistory runs={runs} activeRunId={null} />)
    const sel = screen.getByLabelText(/filter by status/i)
    await user.selectOptions(sel, 'error')
    expect(screen.queryByText(/second/)).toBeInTheDocument()
    expect(screen.queryByText(/first/)).not.toBeInTheDocument()
  })

  it('combined text + tier + status filters intersect', async () => {
    const user = userEvent.setup()
    const runs = [
      mkRun({ id: 'a', task: 'write tests', tier: 'restricted', status: 'done', started_at: NOW - 100 }),
      mkRun({ id: 'b', task: 'write docs', tier: 'elevated', status: 'done', started_at: NOW - 200 }),
      mkRun({ id: 'c', task: 'write code', tier: 'elevated', status: 'error', started_at: NOW - 300 }),
    ]
    render(<RunHistory runs={runs} activeRunId={null} />)
    await user.type(screen.getByLabelText(/filter runs by task text/i), 'write')
    await user.selectOptions(screen.getByLabelText(/filter by tier/i), 'elevated')
    await user.selectOptions(screen.getByLabelText(/filter by status/i), 'done')
    expect(screen.queryByText(/write docs/)).toBeInTheDocument()
    expect(screen.queryByText(/write tests/)).not.toBeInTheDocument()
    expect(screen.queryByText(/write code/)).not.toBeInTheDocument()
  })

  it('shows no-runs-match when filters exclude everything', async () => {
    const user = userEvent.setup()
    const runs = [
      mkRun({ id: 'a', task: 'unique-marker', tier: 'restricted', status: 'done', started_at: NOW - 100 }),
    ]
    render(<RunHistory runs={runs} activeRunId={null} />)
    await user.type(screen.getByLabelText(/filter runs by task text/i), 'nope')
    expect(screen.getByText(/no runs match/i)).toBeInTheDocument()
  })
})

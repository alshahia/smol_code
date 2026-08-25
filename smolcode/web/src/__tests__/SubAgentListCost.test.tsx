// Decision 0028 (per-sub-agent cost aggregation): Vitest unit
// tests for the per-sub-agent CostBadge rendering inside
// <SubAgentList>. Covers:
//   - CostBadge appears in each row when cost_usd > 0
//   - "--" placeholder when cost_usd is null/undefined/0
//   - Total chip rendered only when at least one row has cost > 0
//   - Token text reflects tokens_in + tokens_out

import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'

import { axe } from 'vitest-axe'
import { SubAgentList, type SubAgentSummaryWire } from '../components/SubAgentList'

const BASE: SubAgentSummaryWire = {
  id: 'sa1',
  tier: 'restricted',
  specialist: 'default',
  started_at: 100,
  ended_at: 110,
  tokens_in: 1000,
  tokens_out: 500,
  cost_usd: 0.0125,
}

describe('SubAgentList - cost column (decision 0028)', () => {
  it('renders a CostBadge per row with the per-sub-agent USD cost', () => {
    render(<SubAgentList history={[BASE]} />)
    const row = screen.getByTestId('subagent-row')
    const badge = within(row).getByTestId('cost-badge')
    expect(badge).toHaveTextContent('$0.01')
  })

  it('formats small sub-agent cost with 4 decimals', () => {
    render(<SubAgentList history={[{ ...BASE, cost_usd: 0.0005 }]} />)
    const row = screen.getByTestId('subagent-row')
    expect(within(row).getByTestId('cost-badge')).toHaveTextContent('$0.0005')
  })

  it('shows -- when cost_usd is undefined (older server)', () => {
    const { cost_usd: _omit, ...rest } = BASE
    render(<SubAgentList history={[rest]} />)
    const row = screen.getByTestId('subagent-row')
    expect(within(row).getByTestId('cost-badge')).toHaveTextContent('--')
  })

  it('shows $0.00 when cost_usd is 0 (unknown provider rates)', () => {
    render(<SubAgentList history={[{ ...BASE, cost_usd: 0 }]} />)
    const row = screen.getByTestId('subagent-row')
    expect(within(row).getByTestId('cost-badge')).toHaveTextContent('$0.00')
  })

  it('renders token text per row', () => {
    render(<SubAgentList history={[BASE]} />)
    const row = screen.getByTestId('subagent-row')
    expect(within(row).getByText('1,500 tokens')).toBeInTheDocument()
  })

  it('renders 0 tokens when token fields are missing', () => {
    const { tokens_in: _a, tokens_out: _b, ...rest } = BASE
    render(<SubAgentList history={[rest]} />)
    const row = screen.getByTestId('subagent-row')
    expect(within(row).getByText('0 tokens')).toBeInTheDocument()
  })

  it('renders the total chip when at least one row has cost > 0', () => {
    render(
      <SubAgentList
        history={[
          { ...BASE, id: 'sa1', cost_usd: 0.01 },
          { ...BASE, id: 'sa2', cost_usd: 0.02, specialist: 'deploy-staging' },
        ]}
      />,
    )
    const total = screen.getByTestId('subagent-list-total')
    expect(total).toHaveTextContent(/Sub-agents total/)
    // Sum of 0.01 + 0.02 = 0.03, formatted as 2 decimals
    expect(within(total).getByTestId('cost-badge')).toHaveTextContent('$0.03')
  })

  it('hides the total chip when no row has cost > 0', () => {
    render(
      <SubAgentList
        history={[
          { ...BASE, id: 'sa1', cost_usd: 0 },
          { ...BASE, id: 'sa2', cost_usd: 0 },
        ]}
      />,
    )
    expect(screen.queryByTestId('subagent-list-total')).toBeNull()
  })

  it('still passes axe-core with cost columns present', async () => {
    const { container } = render(<SubAgentList history={[BASE]} />)
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  })
})
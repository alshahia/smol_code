import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { axe } from 'vitest-axe'
import { SubAgentList, type SubAgentSummaryWire } from '../components/SubAgentList'

const SAMPLE: SubAgentSummaryWire[] = [
  { id: 's1', tier: 'restricted', specialist: 'default', started_at: 100, ended_at: 110 },
  { id: 's2', tier: 'elevated', specialist: 'deploy-staging', started_at: 200, ended_at: 305 },
  { id: 's3', tier: 'restricted', started_at: 300, ended_at: null },
]

describe('SubAgentList', () => {
  it('returns null when history is empty', () => {
    const { container } = render(<SubAgentList history={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders one row per sub-agent', () => {
    render(<SubAgentList history={SAMPLE} />)
    const rows = screen.getAllByTestId('subagent-row')
    expect(rows).toHaveLength(3)
  })

  it('shows the tier name on each row', () => {
    render(<SubAgentList history={SAMPLE} />)
    expect(screen.getAllByText('restricted').length).toBeGreaterThan(0)
    expect(screen.getByText('elevated')).toBeInTheDocument()
  })

  it('shows specialist name when present', () => {
    render(<SubAgentList history={SAMPLE} />)
    expect(screen.getByText('deploy-staging')).toBeInTheDocument()
  })

  it('formats duration for completed sub-agents', () => {
    render(<SubAgentList history={SAMPLE} />)
    // s1: 100 -> 110 = 10s, s2: 200 -> 305 = 105s = 1m 45s
    expect(screen.getByText('10.0s')).toBeInTheDocument()
    expect(screen.getByText('1m 45s')).toBeInTheDocument()
  })

  it('shows running marker for non-completed sub-agents', () => {
    render(<SubAgentList history={SAMPLE} />)
    const running = screen.getByText(/running/)
    expect(running).toBeInTheDocument()
  })

  it('toggles list visibility on button click', async () => {
    const user = userEvent.setup()
    render(<SubAgentList history={SAMPLE} />)
    expect(screen.getAllByTestId('subagent-row')).toHaveLength(3)
    const toggle = screen.getByRole('button', { name: /Sub-agents/ })
    await user.click(toggle)
    expect(screen.queryAllByTestId('subagent-row')).toHaveLength(0)
  })

  it('is accessible (axe-core)', async () => {
    const { container } = render(<SubAgentList history={SAMPLE} />)
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  })
})
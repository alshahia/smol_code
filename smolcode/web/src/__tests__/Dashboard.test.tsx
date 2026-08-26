import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

import { axe } from 'vitest-axe'
import { Dashboard } from '../components/Dashboard'
import * as api from '../api'

const SAMPLE: api.DashboardResponse = {
  runs_today: 3,
  tokens_today: { input: 1000, output: 500, total: 1500, cost_usd: 0.0125 },
  errors_today: 1,
  by_provider: {
    openai: { input: 700, output: 300, total: 1000, cost_usd: 0.0084 },
    anthropic: { input: 300, output: 200, total: 500, cost_usd: 0.0041 },
  },
  sparkline: [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120,
    130, 140, 150, 160, 170, 180, 190, 200, 210, 220, 230, 240],
  cost_estimate_usd_today: 0.0125,
  generated_at: 1.0,
}

const NO_CAPS: api.CostCapsState = {
  caps: [],
  defaults: [],
  providers: [],
  current_spend_usd: {},
}

describe('Dashboard', () => {
  beforeEach(() => {
    vi.spyOn(api, 'getDashboard').mockResolvedValue(SAMPLE)
    vi.spyOn(api, 'getCostCaps').mockResolvedValue(NO_CAPS)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the four stat cards', async () => {
    render(<Dashboard />)
    await waitFor(() => expect(screen.getByTestId('dashboard-runs-today')).toBeInTheDocument())
    expect(screen.getByTestId('dashboard-runs-today').textContent).toContain('3')
    expect(screen.getByTestId('dashboard-tokens-today').textContent).toContain('1,500')
    expect(screen.getByTestId('dashboard-errors-today').textContent).toContain('1')
    expect(screen.getByTestId('dashboard-cost-today').textContent).toContain('$0.01')
  })

  it('renders the sparkline as an SVG', async () => {
    render(<Dashboard />)
    const spark = await screen.findByTestId('dashboard-sparkline')
    expect(spark.tagName).toBe('svg')
    expect(spark.querySelector('path')).not.toBeNull()
  })

  it('renders the per-provider table', async () => {
    render(<Dashboard />)
    await screen.findByText('openai')
    expect(screen.getByText('openai')).toBeInTheDocument()
    expect(screen.getByText('anthropic')).toBeInTheDocument()
  })

  it('shows empty state when no providers', async () => {
    vi.spyOn(api, 'getDashboard').mockResolvedValue({ ...SAMPLE, by_provider: {}, runs_today: 0, tokens_today: { input: 0, output: 0, total: 0, cost_usd: 0 } })
    render(<Dashboard />)
    expect(await screen.findByText(/No runs yet today/)).toBeInTheDocument()
  })

  it('shows cost as -- when zero', async () => {
    vi.spyOn(api, 'getDashboard').mockResolvedValue({ ...SAMPLE, cost_estimate_usd_today: 0 })
    render(<Dashboard />)
    await screen.findByTestId('dashboard-cost-today')
    expect(screen.getByTestId('dashboard-cost-today').textContent).toContain('--')
  })

  it('shows error state when fetch fails', async () => {
    vi.spyOn(api, 'getDashboard').mockRejectedValue(new Error('boom'))
    render(<Dashboard />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/boom/)
  })

  it('renders the cost + cap columns when caps are configured', async () => {
    vi.spyOn(api, 'getCostCaps').mockResolvedValue({
      caps: [{ provider: 'openai', cap_usd: 1.0 }],
      defaults: [{ provider: 'openai', cap_usd: 1.0 }],
      providers: ['openai'],
      current_spend_usd: { openai: 0.0084 },
    })
    render(<Dashboard />)
    await screen.findByTestId('dashboard-provider-table')
    expect(screen.getByTestId('dashboard-provider-row-openai')).toBeInTheDocument()
    expect(screen.getByTestId('dashboard-cap-progress-openai')).toBeInTheDocument()
  })

  it('marks over-cap rows', async () => {
    vi.spyOn(api, 'getCostCaps').mockResolvedValue({
      caps: [{ provider: 'openai', cap_usd: 0.005 }],
      defaults: [],
      providers: ['openai'],
      current_spend_usd: { openai: 0.0084 },
    })
    render(<Dashboard />)
    await screen.findByTestId('dashboard-provider-row-openai')
    expect(screen.getByTestId('dashboard-provider-row-openai').className).toContain('over-cap')
  })

  it('is accessible (axe-core)', async () => {
    const { container } = render(<Dashboard />)
    await waitFor(() => expect(screen.getByTestId('dashboard-runs-today')).toBeInTheDocument())
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  })
})
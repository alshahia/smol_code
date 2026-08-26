// decision 0032: tests for the UsageLimitsPanel component.
// Covers the GET / PUT round-trip with mocked API, the empty-state,
// the over-cap row class, and the saved-flash feedback after save.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { UsageLimitsPanel } from '../components/UsageLimitsPanel'
import * as api from '../api'

const BASE_STATE: api.CostCapsState = {
  caps: [{ provider: 'openai', cap_usd: 1.0 }],
  defaults: [{ provider: 'openai', cap_usd: 1.0 }],
  providers: ['openai', 'anthropic'],
  current_spend_usd: { openai: 0.25, anthropic: 0 },
}

describe('UsageLimitsPanel', () => {
  beforeEach(() => {
    vi.spyOn(api, 'getCostCaps').mockResolvedValue(BASE_STATE)
    vi.spyOn(api, 'putCostCaps').mockResolvedValue({
      ...BASE_STATE,
      updated_at: 1700000000,
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the providers and the seeded cap value', async () => {
    render(<UsageLimitsPanel />)
    await waitFor(() => expect(screen.getByTestId('usage-limits-table')).toBeInTheDocument())
    const openaiInput = screen.getByTestId('usage-limits-input-openai') as HTMLInputElement
    expect(openaiInput.value).toBe('1')
    expect(screen.getByTestId('usage-limits-row-openai')).toHaveTextContent('openai')
    expect(screen.getByTestId('usage-limits-row-anthropic')).toHaveTextContent('anthropic')
  })

  it('marks rows as over when today >= cap', async () => {
    vi.spyOn(api, 'getCostCaps').mockResolvedValue({
      ...BASE_STATE,
      caps: [{ provider: 'openai', cap_usd: 0.1 }],
      current_spend_usd: { openai: 0.25, anthropic: 0 },
    })
    render(<UsageLimitsPanel />)
    await waitFor(() => expect(screen.getByTestId('usage-limits-row-openai')).toBeInTheDocument())
    expect(screen.getByTestId('usage-limits-row-openai').className).toContain('over')
  })

  it('PUTs only positive numeric drafts and skips blanks', async () => {
    const user = userEvent.setup()
    const put = vi.spyOn(api, 'putCostCaps')
    render(<UsageLimitsPanel />)
    await waitFor(() => expect(screen.getByTestId('usage-limits-input-openai')).toBeInTheDocument())
    await user.clear(screen.getByTestId('usage-limits-input-openai'))
    await user.type(screen.getByTestId('usage-limits-input-anthropic'), '2.5')
    await user.click(screen.getByTestId('usage-limits-save'))
    await waitFor(() => expect(put).toHaveBeenCalled())
    const payload = put.mock.calls[0]?.[0] as Record<string, number>
    expect(payload).not.toHaveProperty('openai')
    expect(payload.anthropic).toBeCloseTo(2.5)
  })

  it('shows the saved-flash chip after a successful save', async () => {
    const user = userEvent.setup()
    render(<UsageLimitsPanel />)
    await waitFor(() => expect(screen.getByTestId('usage-limits-save')).toBeInTheDocument())
    await user.click(screen.getByTestId('usage-limits-save'))
    expect(await screen.findByTestId('usage-limits-saved-flash')).toHaveTextContent(/saved/i)
  })

  it('reset sends an empty body and clears drafts', async () => {
    const user = userEvent.setup()
    const put = vi.spyOn(api, 'putCostCaps').mockResolvedValue({
      ...BASE_STATE,
      caps: [],
      updated_at: 1700000001,
    })
    render(<UsageLimitsPanel />)
    await waitFor(() => expect(screen.getByTestId('usage-limits-input-openai')).toBeInTheDocument())
    await user.click(screen.getByTestId('usage-limits-reset'))
    await waitFor(() => expect(put).toHaveBeenCalledWith({}))
    const openaiInput = screen.getByTestId('usage-limits-input-openai') as HTMLInputElement
    expect(openaiInput.value).toBe('')
  })

  it('renders the empty-state when no providers are known', async () => {
    vi.spyOn(api, 'getCostCaps').mockResolvedValue({
      caps: [],
      defaults: [],
      providers: [],
      current_spend_usd: {},
    })
    render(<UsageLimitsPanel />)
    expect(await screen.findByText(/no providers are known yet/i)).toBeInTheDocument()
  })

  it('shows an error message when the initial GET fails', async () => {
    vi.spyOn(api, 'getCostCaps').mockRejectedValue(new Error('boom'))
    render(<UsageLimitsPanel />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/boom/)
  })
})
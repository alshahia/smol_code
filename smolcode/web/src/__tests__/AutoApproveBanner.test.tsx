// v1.9.x (FE-6, B10): tests for the AutoApproveBanner component.
// The banner appears in the App shell while auto-approve is active for the
// current run; clicking Disable invokes onDisable.

import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { AutoApproveBanner } from '../components/AutoApproveBanner'

describe('AutoApproveBanner', () => {
  it('does not render when no runId is provided', () => {
    const { container } = render(<AutoApproveBanner runId={null} onDisable={() => {}} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders the banner with active text when runId is provided', () => {
    render(<AutoApproveBanner runId="run-1234" onDisable={() => {}} />)
    expect(screen.getByTestId('auto-approve-banner')).toBeInTheDocument()
    expect(screen.getByTestId('auto-approve-banner')).toHaveTextContent(/auto-approve is on/i)
    expect(screen.getByRole('button', { name: /disable/i })).toBeInTheDocument()
  })

  it('exposes a role=status for assistive tech', () => {
    render(<AutoApproveBanner runId="run-1234" onDisable={() => {}} />)
    expect(screen.getByTestId('auto-approve-banner')).toHaveAttribute('role', 'status')
  })

  it('Disable button invokes onDisable', async () => {
    const user = userEvent.setup()
    const onDisable = vi.fn()
    render(<AutoApproveBanner runId="run-1234" onDisable={onDisable} />)
    await user.click(screen.getByRole('button', { name: /disable/i }))
    expect(onDisable).toHaveBeenCalledTimes(1)
  })
})

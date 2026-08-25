// v1.9.x (FE-6): the ApprovalModal now exposes an optional
// onAutoApproveToggle callback that fires when the user clicks
// "Approve (no more prompts this run)" so the parent can render a
// mid-run "Auto-approve is ON" banner with a Disable button.

import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { ApprovalModal, type PendingApproval } from '../components/ApprovalModal'

const PENDING: PendingApproval = {
  decisionId: 'd-1',
  tool: 'shell',
  args: { cmd: 'rm -rf /' },
  summary: 'destructive tool',
  kind: 'destructive',
}

describe('ApprovalModal', () => {
  it('existing approve calls onDecide', async () => {
    const user = userEvent.setup()
    const onDecide = vi.fn()
    render(<ApprovalModal pending={PENDING} onDecide={onDecide} />)
    await user.click(screen.getByRole('button', { name: /^approve$/i }))
    expect(onDecide).toHaveBeenCalledWith(true, 'user-approved', null)
  })

  it('auto-approve button calls onDecide with reason="auto-approve"', async () => {
    const user = userEvent.setup()
    const onDecide = vi.fn()
    render(<ApprovalModal pending={PENDING} onDecide={onDecide} />)
    await user.click(screen.getByRole('button', { name: /no more prompts/i }))
    expect(onDecide).toHaveBeenCalledWith(true, 'auto-approve', null)
  })

  it('auto-approve button also fires onAutoApproveToggle(true)', async () => {
    const user = userEvent.setup()
    const onDecide = vi.fn()
    const onAutoApproveToggle = vi.fn()
    render(
      <ApprovalModal
        pending={PENDING}
        onDecide={onDecide}
        onAutoApproveToggle={onAutoApproveToggle}
      />,
    )
    await user.click(screen.getByRole('button', { name: /no more prompts/i }))
    expect(onAutoApproveToggle).toHaveBeenCalledWith(true)
  })

  it('regular approve does NOT fire onAutoApproveToggle', async () => {
    const user = userEvent.setup()
    const onDecide = vi.fn()
    const onAutoApproveToggle = vi.fn()
    render(
      <ApprovalModal
        pending={PENDING}
        onDecide={onDecide}
        onAutoApproveToggle={onAutoApproveToggle}
      />,
    )
    await user.click(screen.getByRole('button', { name: /^approve$/i }))
    expect(onAutoApproveToggle).not.toHaveBeenCalled()
  })

  it('deny clears any auto-approve callback (does not fire onAutoApproveToggle)', async () => {
    const user = userEvent.setup()
    const onDecide = vi.fn()
    const onAutoApproveToggle = vi.fn()
    render(
      <ApprovalModal
        pending={PENDING}
        onDecide={onDecide}
        onAutoApproveToggle={onAutoApproveToggle}
      />,
    )
    await user.click(screen.getByRole('button', { name: /^deny$/i }))
    expect(onDecide).toHaveBeenCalledWith(false, 'user-denied', null)
    expect(onAutoApproveToggle).not.toHaveBeenCalled()
  })
})

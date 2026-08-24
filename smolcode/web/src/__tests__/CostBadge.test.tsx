import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import { CostBadge } from '../components/CostBadge'

describe('CostBadge', () => {
  it('formats zero as $0.00', () => {
    render(<CostBadge costUsd={0} rateSource="default" />)
    expect(screen.getByTestId('cost-badge')).toHaveTextContent('$0.00')
  })

  it('formats small values with 4 decimals', () => {
    render(<CostBadge costUsd={0.0005} rateSource="default" />)
    expect(screen.getByTestId('cost-badge')).toHaveTextContent('$0.0005')
  })

  it('formats normal values with 2 decimals', () => {
    render(<CostBadge costUsd={1.234} rateSource="default" />)
    expect(screen.getByTestId('cost-badge')).toHaveTextContent('$1.23')
  })

  it('shows -- when costUsd is null', () => {
    render(<CostBadge costUsd={null} />)
    expect(screen.getByTestId('cost-badge')).toHaveTextContent('--')
  })

  it('shows -- when costUsd is undefined', () => {
    render(<CostBadge costUsd={undefined} />)
    expect(screen.getByTestId('cost-badge')).toHaveTextContent('--')
  })

  it('sets aria-label from rateSource', () => {
    render(<CostBadge costUsd={1} rateSource="override" />)
    expect(screen.getByTestId('cost-badge')).toHaveAttribute(
      'aria-label',
      expect.stringContaining('override'),
    )
  })

  it('shows rateSource tag when detailed=true', () => {
    render(<CostBadge costUsd={1} rateSource="override" detailed />)
    expect(screen.getByTestId('cost-badge')).toHaveTextContent('override')
  })

  it('hides rateSource tag when detailed=false', () => {
    render(<CostBadge costUsd={1} rateSource="override" />)
    const badge = screen.getByTestId('cost-badge')
    expect(badge.textContent).not.toContain('override')
  })

  it('hides rateSource tag for unknown source even when detailed=true', () => {
    render(<CostBadge costUsd={1} rateSource="unknown" detailed />)
    expect(screen.getByTestId('cost-badge')).toHaveTextContent('$1.00')
    expect(screen.getByTestId('cost-badge').textContent).not.toContain('unknown')
  })
})
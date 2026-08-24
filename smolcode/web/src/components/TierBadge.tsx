// Tier badge: always-visible colored chip in the header.
// Color follows the design doc: green (restricted) / amber (elevated) / red (full_access).
import type { FC } from 'react'

const COLORS: Record<string, string> = {
  restricted: '#22c55e',
  elevated: '#f59e0b',
  full_access: '#ef4444',
}

export const TierBadge: FC<{ tier: string }> = ({ tier }) => {
  const color = COLORS[tier] ?? '#6b7280'
  return (
    <span
      className="tier-badge"
      style={{ backgroundColor: color }}
      title={`Active tier: ${tier}`}
    >
      <span className="tier-dot" />
      {tier}
    </span>
  )
}
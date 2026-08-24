// TierSwitcher: header dropdown. Selects the tier for the NEXT run.
// full_access is omitted because the server rejects it (decision 0012).
import type { ChangeEvent } from 'react'

interface Props {
  value: string
  tiers: string[]
  onChange: (tier: string) => void
}

export function TierSwitcher({ value, tiers, onChange }: Props) {
  const handle = (e: ChangeEvent<HTMLSelectElement>) => onChange(e.target.value)
  return (
    <select
      className="tier-switcher"
      value={value}
      onChange={handle}
      title="Tier for the next run"
    >
      {tiers.map((t) => (
        <option key={t} value={t}>
          {t}
        </option>
      ))}
    </select>
  )
}
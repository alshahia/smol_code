// TierSwitcher: header dropdown. Selects the tier for the NEXT run.
// full_access is omitted because the server rejects it (decision 0012).
//
// Phase 0 (decision 0025, FE-5): if localStorage has a `full_access`
// selection from a previous session AND the API rejects it (server
// returns 403 on POST /api/runs), the switcher falls back to
// `restricted` and shows a small inline warning toast. The toast is
// stored in localStorage so it survives reloads; the user dismisses
// it via a X button.
import { useState } from 'react'
import type { ChangeEvent } from 'react'

const LS_KEY = 'smolcode.tierSwitcher.warning.v1'
const FULL_ACCESS = 'full_access'

interface Props {
  value: string
  tiers: string[]
  onChange: (tier: string) => void
}

export function TierSwitcher({ value, tiers, onChange }: Props) {
  const handle = (e: ChangeEvent<HTMLSelectElement>) => onChange(e.target.value)
  const [warning, setWarning] = useState<string | null>(null)
  // Phase 0 (decision 0025, FE-5): the dismissal flag is read once on
  // mount (localStorage). The setter is intentionally unused because
  // we only need to check "was this previously dismissed" -- we do not
  // need to write a new value (dismiss() persists directly).
  const [dismissed] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false
    try {
      return window.localStorage.getItem(LS_KEY) === 'dismissed'
    } catch {
      return false
    }
  })

  // Phase 0 (decision 0025, FE-5): the fallback + warning are derived
  // directly from the render props (no useEffect needed). When the
  // persisted value is full_access AND full_access is not in the
  // available tiers (the server rejects it), we fall back to the
  // first available tier (typically restricted) and show a one-shot
  // warning. The parent onChange fires once on the first render; the
  // warning is shown until the user dismisses it.
  const needsFallback = !dismissed && value === FULL_ACCESS && !tiers.includes(FULL_ACCESS)
  if (needsFallback) {
    const fallback = tiers[0] || 'restricted'
    // Schedule the parent update + warning via microtask to avoid
    // set-state-in-render + parent-during-render warnings.
    queueMicrotask(() => {
      onChange(fallback)
      setWarning('full_access tier is not supported by the web GUI; falling back to ' + fallback + '.')
    })
  }

  const dismiss = () => {
    setWarning(null)
    try {
      if (typeof window !== 'undefined') window.localStorage.setItem(LS_KEY, 'dismissed')
    } catch {
      /* ignore */
    }
  }

  return (
    <span className="tier-switcher-wrap">
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
      {warning && (
        <span className="tier-switcher-warning warn-banner" role="alert">
          {warning}
          <button type="button" className="btn btn-sm btn-secondary" onClick={dismiss} aria-label="Dismiss">
            ×
          </button>
        </span>
      )}
    </span>
  )
}
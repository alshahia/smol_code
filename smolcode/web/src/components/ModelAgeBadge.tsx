// ModelAgeBadge: tiny chip showing how old the cached model list is (M12).
// Hidden when no fetch has happened yet (cachedAt === null).
// Buckets mirror the CLI smolcode models list formatter
// (model_catalog._models_format_age / decision 0015):
//   <30s  -> "just now"     <60s  -> "Ns ago"
//   <1h   -> "Nm ago"       <24h  -> "Nh ago"
//   else  -> "Nd ago"
// Re-renders every 30s so the chip stays fresh without spamming React.
//
// M12.4: when ``cachedError`` is non-null, render a warning-style chip
// instead. The label is prefixed with "!" and the full error is shown
// via the title attribute so hovering reveals the underlying message
// without truncating it inline.

import { useEffect, useState } from 'react'

interface Props {
  /** Epoch seconds of the most recent model-list fetch, or null if never fetched. */
  cachedAt: number | null
  /** M12.4: short error from the most recent failed fetch, or null. */
  cachedError?: string | null
}

const REFRESH_INTERVAL_MS = 30_000

function formatAge(cachedAt: number, now: number): string {
  const age = Math.max(0, now - cachedAt)
  if (age < 30) return 'just now'
  if (age < 60) return Math.round(age) + 's ago'
  if (age < 3600) return Math.round(age / 60) + 'm ago'
  if (age < 86400) return Math.round(age / 3600) + 'h ago'
  return Math.round(age / 86400) + 'd ago'
}

export function ModelAgeBadge({ cachedAt, cachedError }: Props) {
  const [now, setNow] = useState<number>(() => Date.now())

  useEffect(() => {
    if (cachedAt === null) return
    const id = window.setInterval(() => setNow(Date.now()), REFRESH_INTERVAL_MS)
    return () => window.clearInterval(id)
  }, [cachedAt])

  if (cachedAt === null) return null

  const label = formatAge(cachedAt, now)
  const iso = new Date(cachedAt * 1000).toISOString()
  // M12.4: when the most recent fetch FAILED, show a warning chip.
  // Hovering reveals the full error string; the label keeps the age
  // so the user can tell whether to retry now or wait.
  if (cachedError) {
    return (
      <span
        className="model-age-badge error small"
        title={
          'Last fetch failed at ' + iso + ': ' + cachedError
        }
        aria-label={
          'Model list last fetch failed (' + label + ', ' + iso + '): ' + cachedError
        }
      >
        {'! ' + label + ' · fetch failed'}
      </span>
    )
  }

  return (
    <span
      className="model-age-badge small muted"
      title={'Model list fetched at ' + iso}
      aria-label={'Model list last fetched ' + label + ' (' + iso + ')'}
    >
      {'· ' + label}
    </span>
  )
}

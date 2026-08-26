// UsageLimitsPanel (decision 0032): per-provider USD cap editor.
// Mounts inside the Dashboard overlay (App.tsx). Lets the user
// edit a cap per provider, see today's spend for that provider,
// and persist via PUT /api/cost-caps. GET happens once on mount;
// PUT responses are reflected immediately (we trust the echo and
// merge it into local state). The provider list is the union of
// the BE's known providers + the providers that already have a
// cap (so an offline SPA still shows the rows it knows about).

import { useEffect, useState } from 'react'

import {
  getCostCaps,
  putCostCaps,
  type CostCapsState,
} from '../api'

interface DraftRow {
  provider: string
  /** Local draft cap (string so we can keep empty / partial input). */
  capDraft: string
}

function buildRows(state: CostCapsState): DraftRow[] {
  // Union: every provider the BE knows about + every provider that
  // already has a cap (in case the BE ever trims its list).
  const providers = new Set<string>(state.providers)
  for (const c of state.caps) providers.add(c.provider)
  for (const d of state.defaults) providers.add(d.provider)
  return Array.from(providers).sort().map((p) => {
    const existing = state.caps.find((c) => c.provider === p)
    return { provider: p, capDraft: existing ? String(existing.cap_usd) : '' }
  })
}

function dollars(n: number): string {
  if (!isFinite(n) || n <= 0) return '--'
  return '$' + n.toFixed(2)
}

export function UsageLimitsPanel(): React.JSX.Element {
  const [state, setState] = useState<CostCapsState | null>(null)
  const [rows, setRows] = useState<DraftRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [savedFlash, setSavedFlash] = useState<number>(0)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  // Load on mount; do not poll (the panel is a deliberate user-driven
  // edit surface, not a live gauge -- Dashboard.tsx already polls the
  // spend + cap columns on its 30s tick).
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const s = await getCostCaps()
        if (cancelled) return
        setState(s)
        setRows(buildRows(s))
        setError(null)
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'fetch failed')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const handleDraftChange = (provider: string, value: string) => {
    setRows((prev) =>
      prev.map((r) => (r.provider === provider ? { ...r, capDraft: value } : r)),
    )
  }

  const handleSave = async () => {
    if (!state || saving) return
    // Build the new caps payload: only include rows with a non-empty
    // positive number. Empty/missing/zero/negative all mean 'no cap'.
    const caps: Record<string, number> = {}
    for (const r of rows) {
      const trimmed = r.capDraft.trim()
      if (trimmed.length === 0) continue
      const n = Number(trimmed)
      if (!isFinite(n) || n <= 0) continue
      caps[r.provider] = n
    }
    setSaving(true)
    setError(null)
    try {
      const resp = await putCostCaps(caps)
      setState({
        caps: resp.caps,
        defaults: resp.defaults,
        providers: resp.providers,
        current_spend_usd: state.current_spend_usd,
      })
      setRows(buildRows(resp))
      setSavedFlash(Date.now())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'save failed')
    } finally {
      setSaving(false)
    }
  }

  const handleReset = async () => {
    if (!state || saving) return
    setSaving(true)
    setError(null)
    try {
      // Empty body => BE clears overrides (defaults stay as-is).
      const resp = await putCostCaps({})
      setState({
        caps: resp.caps,
        defaults: resp.defaults,
        providers: resp.providers,
        current_spend_usd: state.current_spend_usd,
      })
      setRows(buildRows(resp))
      setSavedFlash(Date.now())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'reset failed')
    } finally {
      setSaving(false)
    }
  }

  if (loading && !state) {
    return <div className="usage-limits" aria-busy="true">Loading usage limits…</div>
  }
  if (error && !state) {
    return (
      <div className="usage-limits" role="alert">
        <div className="usage-limits-error">Failed to load usage limits: {error}</div>
      </div>
    )
  }
  if (!state) return <div className="usage-limits">No usage limits configured.</div>

  return (
    <section className="usage-limits" aria-label="Usage limits">
      <header className="usage-limits-header">
        <h3>Usage limits</h3>
        <p className="usage-limits-help">
          Set a per-provider USD cap. New runs are rejected once today's spend for that
          provider reaches the cap. Values can be fractional; <code>0</code> or empty
          means "no cap". Set via <code>SMOLCODE_COST_CAPS</code> env var to seed defaults.
        </p>
      </header>
      {error && (
        <div className="usage-limits-error" role="alert">
          {error}
        </div>
      )}
      {rows.length === 0 ? (
        <p className="usage-limits-help">No providers are known yet. Start a run to populate this list.</p>
      ) : (
        <table className="usage-limits-table" data-testid="usage-limits-table">
          <thead>
            <tr>
              <th>Provider</th>
              <th>Today</th>
              <th>Cap (USD)</th>
              <th>Progress</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const capNum = Number(r.capDraft)
              const hasCap = r.capDraft.trim().length > 0 && isFinite(capNum) && capNum > 0
              const today = state.current_spend_usd[r.provider] ?? 0
              const over = hasCap && today >= capNum
              const pct = hasCap ? Math.min(100, Math.round((today / capNum) * 100)) : 0
              return (
                <tr
                  key={r.provider}
                  className={over ? 'usage-limits-row over' : 'usage-limits-row'}
                  data-testid={'usage-limits-row-' + r.provider}
                >
                  <td>{r.provider}</td>
                  <td>{dollars(today)}</td>
                  <td>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      inputMode="decimal"
                      value={r.capDraft}
                      aria-label={'cap for ' + r.provider}
                      data-testid={'usage-limits-input-' + r.provider}
                      onChange={(e) => handleDraftChange(r.provider, e.target.value)}
                    />
                  </td>
                  <td>
                    {hasCap ? (
                      <progress
                        max={100}
                        value={pct}
                        aria-label={pct + '% of cap for ' + r.provider}
                        data-testid={'usage-limits-progress-' + r.provider}
                      />
                    ) : (
                      <span className="usage-limits-no-cap">--</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      <footer className="usage-limits-footer">
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => void handleSave()}
          disabled={saving}
          data-testid="usage-limits-save"
        >
          {saving ? 'Saving…' : 'Save caps'}
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => void handleReset()}
          disabled={saving}
          data-testid="usage-limits-reset"
        >
          Reset to defaults
        </button>
        {savedFlash > 0 && (
          <span className="usage-limits-saved-flash" data-testid="usage-limits-saved-flash">
            Saved.
          </span>
        )}
      </footer>
    </section>
  )
}
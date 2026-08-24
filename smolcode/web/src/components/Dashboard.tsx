// Phase 3 (decision 0025 sec 6.5 / FE-1): Dashboard tab.
// Top: 3 stat cards (runs today / tokens today / errors today).
// Middle: 24-hour token sparkline (SVG line chart, no external libs).
// Bottom: per-provider token + cost breakdown.
// Refreshes every 30s via setInterval (cleanup-wired for React 19 StrictMode).

import React, { useEffect, useState } from 'react'

import { getDashboard, type DashboardResponse } from '../api'

const REFRESH_MS = 30000

export function Dashboard(): React.JSX.Element {
  const [data, setData] = useState<DashboardResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function load(): Promise<void> {
      try {
        const d = await getDashboard()
        if (!cancelled) {
          setData(d)
          setError(null)
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'fetch failed')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    const t = window.setInterval(load, REFRESH_MS)
    return () => {
      cancelled = true
      window.clearInterval(t)
    }
  }, [])

  if (loading && !data) {
    return <div className="dashboard dashboard-loading" aria-busy="true">Loading dashboard…</div>
  }
  if (error && !data) {
    return <div className="dashboard dashboard-error" role="alert">Failed to load dashboard: {error}</div>
  }
  if (!data) return <div className="dashboard">No data.</div>

  const sparkMax = Math.max(1, ...data.sparkline)
  const sparkPath = data.sparkline
    .map((v, i) => {
      const x = (i / (data.sparkline.length - 1 || 1)) * 100
      const y = 100 - (v / sparkMax) * 100
      return (i === 0 ? 'M' : 'L') + x.toFixed(2) + ',' + y.toFixed(2)
    })
    .join(' ')

  return (
    <div className="dashboard" aria-label="Dashboard">
      <div className="dashboard-stats">
        <article className="dashboard-card" data-testid="dashboard-runs-today">
          <h3>Runs today</h3>
          <p className="dashboard-card-value">{data.runs_today}</p>
        </article>
        <article className="dashboard-card" data-testid="dashboard-tokens-today">
          <h3>Tokens today</h3>
          <p className="dashboard-card-value">{data.tokens_today.total.toLocaleString()}</p>
          <p className="dashboard-card-sub">
            {data.tokens_today.input.toLocaleString()} in / {data.tokens_today.output.toLocaleString()} out
          </p>
        </article>
        <article className="dashboard-card" data-testid="dashboard-errors-today">
          <h3>Errors today</h3>
          <p className={'dashboard-card-value ' + (data.errors_today > 0 ? 'has-errors' : '')}>
            {data.errors_today}
          </p>
        </article>
        <article className="dashboard-card" data-testid="dashboard-cost-today">
          <h3>Cost today</h3>
          <p className="dashboard-card-value">
            {data.cost_estimate_usd_today > 0 ? '$' + data.cost_estimate_usd_today.toFixed(2) : '--'}
          </p>
        </article>
      </div>

      <section className="dashboard-sparkline-section" aria-label="24h token sparkline">
        <h3>Tokens last 24h</h3>
        <svg
          data-testid="dashboard-sparkline"
          className="dashboard-sparkline"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          role="img"
          aria-label={`24-hour sparkline: ${data.tokens_today.total} tokens total`}
        >
          <path d={sparkPath} fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </section>

      <section className="dashboard-providers" aria-label="Per-provider breakdown">
        <h3>By provider (today)</h3>
        {Object.keys(data.by_provider).length === 0 ? (
          <p className="dashboard-empty">No runs yet today.</p>
        ) : (
          <table className="dashboard-provider-table">
            <thead>
              <tr><th>Provider</th><th>In</th><th>Out</th><th>Total</th></tr>
            </thead>
            <tbody>
              {Object.entries(data.by_provider).map(([prov, t]) => (
                <tr key={prov}>
                  <td>{prov}</td>
                  <td>{t.input.toLocaleString()}</td>
                  <td>{t.output.toLocaleString()}</td>
                  <td>{t.total.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
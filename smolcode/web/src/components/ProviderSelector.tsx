// ProviderSelector: dropdown over GET /api/providers (M11).
// Shows key_state badge per provider and a model count after a refresh.
// Emits (providerId, defaultModel) so callers can hydrate the model field.
import { useEffect, useState } from 'react'
import type { ChangeEvent } from 'react'
import { listProviders, listProviderModels, type ProviderInfo } from '../api'
import { ModelAgeBadge } from './ModelAgeBadge'

interface Props {
  value: string | null
  onChange: (providerId: string, defaultModel: string) => void
}

interface ModelState {
  loading: boolean
  count: number | null
  error: string | null
}

function badgeFor(info: ProviderInfo): string {
  return info.key_state === 'set' ? '🔑 set' : '∅ missing'
}

export function ProviderSelector({ value, onChange }: Props) {
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [model, setModel] = useState<ModelState>({
    loading: false,
    count: null,
    error: null,
  })

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const r = await listProviders()
        if (!cancelled) {
          setProviders(r.providers)
          setLoading(false)
        }
      } catch (e) {
        if (!cancelled) {
          setLoadError((e as Error).message)
          setLoading(false)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // Refresh model count for the currently-selected provider whenever the
  // selection changes.
  useEffect(() => {
    if (!value) {
      setModel({ loading: false, count: null, error: null })
      return
    }
    const info = providers.find((p) => p.id === value)
    if (!info) {
      setModel({ loading: false, count: null, error: null })
      return
    }
    if (info.model_count !== null) {
      setModel({ loading: false, count: info.model_count, error: null })
      return
    }
    // model_count is null: server has no in-process list yet (anthropic uses
    // hardcoded presets, the rest fetch lazily). Trigger an async fetch so
    // the user sees how many models are available for this provider.
    let cancelled = false
    setModel({ loading: true, count: null, error: null })
    void (async () => {
      try {
        const r = await listProviderModels(value, false)
        if (cancelled) return
        if (r.error) {
          setModel({ loading: false, count: 0, error: r.error })
        } else {
          setModel({ loading: false, count: r.models.length, error: null })
        }
      } catch (e) {
        if (!cancelled) {
          setModel({ loading: false, count: null, error: (e as Error).message })
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [value, providers])

  const handleSelect = (e: ChangeEvent<HTMLSelectElement>) => {
    const id = e.target.value
    const info = providers.find((p) => p.id === id)
    if (info) onChange(info.id, info.default_model)
  }

  const refresh = async () => {
    if (!value) return
    setModel({ loading: true, count: null, error: null })
    try {
      const r = await listProviderModels(value, true)
      if (r.error) {
        setModel({ loading: false, count: 0, error: r.error })
      } else {
        setModel({ loading: false, count: r.models.length, error: null })
      }
    } catch (e) {
      setModel({ loading: false, count: null, error: (e as Error).message })
    }
    // Also refresh the provider catalog so cached_at (for the badge)
    // reflects the just-completed fetch. Silently ignore failures here
    // since the catalog refresh is best-effort UI feedback.
    try {
      const cat = await listProviders()
      setProviders(cat.providers)
    } catch {
      /* ignore */
    }
  }

  if (loading) return <div className="provider-selector muted small">Loading providers…</div>
  if (loadError) {
    return (
      <div className="provider-selector-error">
        <code>{loadError}</code>
      </div>
    )
  }
  if (providers.length === 0) {
    return <div className="muted small">No providers available.</div>
  }

  return (
    <div className="provider-selector">
      <select
        className="provider-select"
        value={value ?? ''}
        onChange={handleSelect}
        title="Select a model provider"
      >
        {providers.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}) {badgeFor(p)} — default: {p.default_model}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="btn btn-sm btn-secondary"
        onClick={refresh}
        disabled={!value || model.loading}
        title="Re-fetch the model list for this provider"
      >
        {model.loading ? '...' : '↻'}
      </button>
      {value && (
        <span className="provider-meta small muted">
          {model.error
            ? `models: error — ${model.error}`
            : model.count === null
              ? 'models: ?'
              : `models: ${model.count}`}
          <ModelAgeBadge
            cachedAt={
              providers.find((p) => p.id === value)?.cached_at ?? null
            }
            cachedError={
              providers.find((p) => p.id === value)?.cached_error ?? null
            }
          />
        </span>
      )}
    </div>
  )
}

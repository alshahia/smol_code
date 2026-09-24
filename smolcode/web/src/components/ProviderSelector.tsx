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

  // The model count is almost entirely DERIVED from props (providers +
  // value), so the whole desired state is computed during render and only
  // the genuinely async fetch needs an effect. Resetting ModelState in an
  // effect on every prop change painted a frame with the previous
  // provider's count and was the set-state-in-effect the linter flagged.
  //
  //   no selection / provider not loaded yet -> empty
  //   model_count known                    -> that count, not loading
  //   model_count null                     -> loading, effect fetches it
  const selected = value ? providers.find((p) => p.id === value) : undefined
  const desired: ModelState =
    !selected || selected.model_count === null
      ? { loading: selected !== undefined, count: null, error: null }
      : { loading: false, count: selected.model_count, error: null }

  const [lastModelKey, setLastModelKey] = useState<string | null>(null)
  const modelKey = selected ? value + ':' + String(selected.model_count) : null
  if (modelKey !== lastModelKey) {
    setLastModelKey(modelKey)
    setModel(desired)
  }

  // Fetch the model list only when the server has no in-process count yet.
  // model_count is null: anthropic uses hardcoded presets, the rest fetch
  // lazily. The result is written straight into state below.
  useEffect(() => {
    if (!value) return
    const info = providers.find((p) => p.id === value)
    if (!info || info.model_count !== null) return
    let cancelled = false
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
        // Phase 5 (ADR 0040): the select had only a `title`, which is a
        // weak accessible-name fallback and gave tests nothing to query
        // by. An explicit aria-label is the name assistive tech actually
        // announces, and it makes the control addressable in tests.
        aria-label="Model provider"
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

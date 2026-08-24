// Main App: 3-pane layout (M9 + M11).
// Header: brand + tier badge + tier switcher + provider selector + api-key panel + workspace
// Left pane (Plan): RunComposer + upload zone + uploads + allowlist + run history
// Center pane (Stream): live event stream for the active run + stop button
// Right pane (Inspector): active run summary + tier policy cards

import { useCallback, useEffect, useMemo, useState } from 'react'
import { TierBadge } from './components/TierBadge'
import { TierSwitcher } from './components/TierSwitcher'
import { UploadDropZone } from './components/UploadDropZone'
import { UploadList } from './components/UploadList'
import { AllowlistSimulator } from './components/AllowlistSimulator'
import { EventStream } from './components/EventStream'
import { ApprovalModal, type PendingApproval } from './components/ApprovalModal'
import { StopButton } from './components/StopButton'
import { RunComposer } from './components/RunComposer'
import { RunHistory } from './components/RunHistory'
import { Inspector } from './components/Inspector'
import { ProviderSelector } from './components/ProviderSelector'
import { ApiKeyPanel } from './components/ApiKeyPanel'
import { useMediaQuery } from './lib/useMediaQuery'
import { loadLast, saveLast } from './lib/lastSelection'
import {
  getConfig,
  listProviders,
  listUploads,
  listRuns,
  postApproval,
  type ConfigResponse,
  type ProviderInfo,
  type UploadMetadata,
  type RunSummary,
} from './api'
import { getKey } from './lib/keysStore'

function App() {
  const [config, setConfig] = useState<ConfigResponse | null>(null)
  const [uploads, setUploads] = useState<UploadMetadata[]>([])
  const [tier, setTier] = useState<string>('restricted')
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [activeRun, setActiveRun] = useState<RunSummary | null>(null)
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [pending, setPending] = useState<PendingApproval | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Phase 0 (decision 0025, B11): bumped on every diff.proposed /
  // diff.resolved event so the Inspector's WorkspaceTree refreshes
  // immediately instead of waiting for its 10s poll.
  const [treeRefreshTrigger, setTreeRefreshTrigger] = useState<number>(0)

  // M11: provider + model + key state, hoisted to App so RunComposer can read them.
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(null)
  const [selectedModel, setSelectedModel] = useState<string>('')
  const [storedKeyValue, setStoredKeyValue] = useState<string | null>(null)

  // M12.5 (mobile): inspector pane visibility toggle. Persisted to
  // localStorage so the user's choice survives reloads. Default `false`
  // on narrow viewports (the inspector is hidden by default; the user
  // taps the toggle to reveal it). The initial value is read from
  // localStorage via the lazy `useState` initializer — runs ONCE on
  // mount, no useEffect needed for the read. SSR-safe via the standard
  // `typeof window` guard. The persist-back useEffect does NOT call
  // setState (just localStorage.setItem) so it does not raise the
  // `set-state-in-effect` oxlint warning that the M12.2 baseline
  // already has 3 of in sibling components.
  const [inspectorOpen, setInspectorOpen] = useState<boolean>(() => {
    if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') {
      return false
    }
    try {
      return window.localStorage.getItem('smolcode.inspectorOpen.v1') === 'true'
    } catch {
      return false
    }
  })
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') {
      return
    }
    try {
      window.localStorage.setItem('smolcode.inspectorOpen.v1', inspectorOpen ? 'true' : 'false')
    } catch {
      // ignore quota / sandbox errors
    }
  }, [inspectorOpen])

  // M15.3 (decision 0019): matchMedia-driven inspector breakpoint.
  // Replaces the static @media (max-width: 900px) CSS rule from M12.5
  // so the breakpoint respects OS zoom + Windows display scaling.
  // Defaults to false (desktop) when matchMedia is unavailable.
  const isMobile = useMediaQuery('(max-width: 900px)')

  const refreshUploads = useCallback(async () => {
    try {
      const r = await listUploads()
      setUploads(r.uploads)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])

  const refreshRuns = useCallback(async () => {
    try {
      const r = await listRuns()
      setRuns(r.runs)
      // Phase 0 (decision 0025, B9 fix): the previous implementation
      // kept stale activeRun state when the active run was removed
      // server-side (RunManager purged it after the window of history).
      // We now CLEAR activeRun when the active id is no longer in the
      // list -- a graceful "run is gone" UX instead of a 404 explosion
      // in the Inspector.
      const active = r.runs.find((x) => x.id === activeRunId) ?? null
      setActiveRun(active)
    } catch {
      /* ignore transient */
    }
  }, [activeRunId])

  useEffect(() => {
    void (async () => {
      try {
        const c = await getConfig()
        setConfig(c)
        // M12 (decision 0015): on reload, prefer the user's last-used
        // model when the last providerId matches the server default. If
        // the user had picked a different provider last time, that
        // selection is restored later in the providers-list effect below
        // (where we have the catalog to validate against).
        const last = loadLast()
        const restoredProvider = c.provider
        const restoredModel =
          last && last.providerId === c.provider && last.model.length > 0
            ? last.model
            : c.model
        setSelectedProviderId(restoredProvider)
        setSelectedModel(restoredModel)
        await refreshUploads()
        await refreshRuns()
      } catch (e) {
        setError((e as Error).message)
      }
    })()
  }, [refreshUploads, refreshRuns])

  // Load the provider catalog once. If config arrived before this resolves,
  // match the initial selection against the list to grab its full info.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const r = await listProviders()
        if (cancelled) return
        setProviders(r.providers)
        // M12: if the user picked a different provider last session,
        // restore it now that we have the catalog to validate against.
        const last = loadLast()
        if (last && last.providerId.length > 0) {
          const info = r.providers.find((p) => p.id === last.providerId)
          if (info) {
            const m =
              last.model.length > 0 ? last.model : info.default_model
            setSelectedProviderId(info.id)
            setSelectedModel(m)
          }
        }
      } catch (e) {
        // Don't blow up the app if the catalog endpoint fails — just leave
        // the header provider/model label blank.
        if (!cancelled) {
          setProviders([])
        }
        // Surface via setError so users see it once on first load.
        setError((e as Error).message)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // Whenever the selection changes, re-read the localStorage key for it.
  useEffect(() => {
    if (!selectedProviderId) {
      setStoredKeyValue(null)
      return
    }
    setStoredKeyValue(getKey(selectedProviderId))
  }, [selectedProviderId])

  // Poll run history every 5s to keep the list fresh (cheap; loopback).
  useEffect(() => {
    const id = window.setInterval(() => {
      void refreshRuns()
    }, 5000)
    return () => window.clearInterval(id)
  }, [refreshRuns])

  const selectedProvider: ProviderInfo | null = useMemo(() => {
    if (!selectedProviderId) return null
    return providers.find((p) => p.id === selectedProviderId) ?? null
  }, [providers, selectedProviderId])

  const handleProviderChange = (providerId: string, defaultModel: string) => {
    setSelectedProviderId(providerId)
    setSelectedModel(defaultModel)
    // M12 (decision 0015): persist for cross-reload restore.
    saveLast(providerId, defaultModel)
  }

  const handleKeyChange = (_providerId: string, value: string | null) => {
    setStoredKeyValue(value)
  }

  const onSubmitted = (runId: string) => {
    setActiveRunId(runId)
    setActiveRun(null)
    void refreshRuns()
  }

  const onApprovalRequest = (decisionId: string, tool: string, args: unknown, summary: string) => {
    setPending({ decisionId, tool, args, summary, kind: 'destructive' })
  }

  const onDiffProposed = (
    decisionId: string,
    tool: string,
    args: unknown,
    summary: string,
    path: string,
    relPath: string,
    before: string,
    after: string,
    rawDiff: string,
    hunks: unknown,
    stats: unknown,
  ) => {
    setPending({
      decisionId,
      tool,
      args,
      summary,
      kind: 'diff',
      path,
      relPath,
      before,
      after,
      rawDiff,
      hunks: Array.isArray(hunks) ? (hunks as PendingApproval['hunks']) : undefined,
      stats: (stats && typeof stats === 'object') ? (stats as PendingApproval['stats']) : undefined,
    })
    // Phase 0 (decision 0025, B11): bump the tree refresh trigger so
    // the Inspector's WorkspaceTree re-fetches on this event instead
    // of waiting for its 10s poll.
    setTreeRefreshTrigger((n) => n + 1)
    void refreshRuns()
  }

  const onFinal = (_result: string | null, _error: string | null) => {
    void refreshRuns()
  }

  const onDecide = async (approved: boolean, reason: string, editedAfter: string | null) => {
    if (!pending || !activeRunId) return
    const dId = pending.decisionId
    setPending(null)
    try {
      await postApproval(activeRunId, dId, approved, reason, editedAfter)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  if (error) {
    return (
      <div className="error-screen">
        <h1>Cannot reach the smolcode web server</h1>
        <pre>{error}</pre>
        <p>
          Is <code>smolcode web</code> running on <code>http://127.0.0.1:7860</code>?
        </p>
      </div>
    )
  }

  if (!config) {
    return <div className="loading">Loading...</div>
  }

  const tierNames = config.tiers.map((t) => t.name)
  // The header dropdown lists tiers supported by the web API.
  // full_access is intentionally omitted (the API rejects it; decision 0012).
  const switcherTiers = tierNames.filter((t) => t !== 'full_access')
  const runTerminal =
    activeRun !== null &&
    (activeRun.status === 'done' || activeRun.status === 'error' || activeRun.status === 'stopped')

  return (
    <div className="app">
      <header className="header">
        <div className="brand">smolcode</div>
        <TierBadge tier={tier} />
        <TierSwitcher value={tier} tiers={switcherTiers} onChange={setTier} />
        <button
          type="button"
          className="inspector-toggle btn btn-secondary"
          aria-expanded={inspectorOpen}
          aria-controls="inspector-pane"
          // M15.3 (decision 0019): JS-driven visibility so the toggle
          // only appears when the matchMedia breakpoint is active.
          // Replaces the CSS .inspector-toggle { display: none } +
          // @media (max-width: 900px) { .inspector-toggle { display: inline-flex } }
          // pair, which did not respond to OS zoom changes.
          style={{ display: isMobile ? 'inline-flex' : 'none' }}
          onClick={() => setInspectorOpen((v) => !v)}
        >
          {inspectorOpen ? 'Inspector ▴' : 'Inspector ▾'}
        </button>
        <div className="ws" title={config.workspace}>
          {config.workspace.split(/[\\/]/).slice(-2).join('/')}
        </div>
      </header>

      <div className="header-row-m11">
        <ProviderSelector
          value={selectedProviderId}
          onChange={handleProviderChange}
        />
        <div className="model-row">
          <label className="small muted" htmlFor="model-input">
            Model
          </label>
          <input
            id="model-input"
            type="text"
            className="model-input"
            value={selectedModel}
            onChange={(e) => {
              const v = e.target.value
              setSelectedModel(v)
              if (selectedProviderId) saveLast(selectedProviderId, v)
            }}
            placeholder="model-id"
            spellCheck={false}
          />
        </div>
        {selectedProvider && (
          <ApiKeyPanel
            provider={selectedProvider}
            hasStoredKey={storedKeyValue !== null}
            onKeyChange={handleKeyChange}
          />
        )}
      </div>

      <div className="three-pane">
        <aside className="pane plan">
          <section className="plan-task">
            <h3>Task</h3>
            <RunComposer
              tier={tier}
              provider={selectedProviderId}
              model={selectedModel || null}
              keyValue={storedKeyValue}
              apiKeyEnv={selectedProvider?.env_vars[0] ?? null}
              onSubmitted={onSubmitted}
            />
          </section>

          <section className="plan-runs">
            <h3>History</h3>
            <RunHistory
              runs={runs}
              activeRunId={activeRunId}
              onSelect={(id) => setActiveRunId(id)}
            />
          </section>

          <section className="plan-uploads">
            <h3>Uploads ({uploads.length})</h3>
            <UploadDropZone tier="restricted" onUploaded={() => void refreshUploads()} />
            <UploadList uploads={uploads} onDeleted={() => void refreshUploads()} />
          </section>

          <section className="plan-allowlist">
            <AllowlistSimulator tiers={tierNames} defaultTier="restricted" />
          </section>
        </aside>

        <main className="pane stream">
          <div className="stream-header">
            <h3>Execution stream</h3>
            {activeRunId && !runTerminal && <StopButton runId={activeRunId} onStopped={() => void refreshRuns()} />}
          </div>
          {activeRunId ? (
            <EventStream
              runId={activeRunId}
              onApprovalRequest={onApprovalRequest}
              onDiffProposed={onDiffProposed}
              onFinal={onFinal}
            />
          ) : (
            <div className="placeholder">Start a task to see the live stream.</div>
          )}
        </main>

        <aside
          id="inspector-pane"
          className="pane inspector"
          // M15.3 (decision 0019): JS-driven visibility. On desktop
          // (isMobile=false) the inspector is always visible. On mobile
          // it follows `inspectorOpen` (localStorage-persisted).
          style={{ display: isMobile && !inspectorOpen ? 'none' : 'block' }}
        >
          <h3>Inspector</h3>
          <Inspector activeRun={activeRun} config={config} treeRefreshTrigger={treeRefreshTrigger} />
        </aside>
      </div>

      <ApprovalModal pending={pending} onDecide={onDecide} />
    </div>
  )
}

export default App

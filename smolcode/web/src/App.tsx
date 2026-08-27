// Main App: 3-pane layout (M9 + M11).
// Header: brand + tier badge + tier switcher + provider selector + api-key panel + workspace
// Left pane (Plan): RunComposer + upload zone + uploads + allowlist + run history
// Center pane (Stream): live event stream for the active run + stop button
// Right pane (Inspector): active run summary + tier policy cards
//
// v1.9.x (decision 0025 FE-5/6/7/8/9 + PW-4):
//   - Mounts the Phase-3 keyboard router (lib/keyboard.ts) on mount.
//   - Renders <Dashboard> as a modal overlay triggered by a header
//     button (FE-1 + FE-8).
//   - Tracks auto-approve-active flag client-side (Set<runId>) and
//     renders <AutoApproveBanner> when active for the current run
//     (FE-6 / B10).
//   - Renders <RunActions> (Retry / Re-run / Export) in the stream
//     header when the active run is terminal (FE-7 / B4 + B5 + B7).
//   - Forwards onAutoApproveToggle to <ApprovalModal> so the modal can
//     report auto-approve flips to the parent.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
import { SessionsPane } from './components/SessionsPane'
import { ProjectSwitcher } from './components/ProjectSwitcher'
import { QueuePane } from './components/QueuePane'
import { FilePreview } from './components/FilePreview'
// v1.9.x: new components
import { Dashboard } from './components/Dashboard'
import { UsageLimitsPanel } from './components/UsageLimitsPanel'
import { AutoApproveBanner } from './components/AutoApproveBanner'
import { RunActions } from './components/RunActions'
import { installKeyboardRouter } from './lib/keyboard'
import { useMediaQuery } from './lib/useMediaQuery'
import { loadLast, saveLast } from './lib/lastSelection'
import {
  getConfig,
  listProjects,
  listProviders,
  listUploads,
  listRuns,
  postApproval,
  postAutoApprove,
  postOpenPath,
  postStop,
  type ConfigResponse,
  type ProjectInfo,
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
  // Decision 0033: ref mirror of activeRunId so the global keyboard
  // router (installed once, never re-installed) reads the live value at
  // fire-time. Closes a webkit-only race where Ctrl+. fired in the
  // window between setActiveRunId and the next useEffect commit.
  const activeRunIdRef = useRef<string | null>(null)
  useEffect(() => {
    activeRunIdRef.current = activeRunId
  }, [activeRunId])
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

  // M12.5 (mobile): inspector pane visibility toggle.
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

  // Phase 1 (decision 0025 §6.3): active project + chat session.
  const [activeProject, setActiveProjectRaw] = useState<string | null>(() => {
    if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') {
      return null
    }
    try {
      return window.localStorage.getItem('smolcode.activeProject.v1') || null
    } catch {
      return null
    }
  })
  // Phase 2 (decision 0025 §6.4): the path of the file currently shown
  // in the <FilePreview> pane.
  const [filePreviewPath, setFilePreviewPath] = useState<string | null>(null)
  // Phase 2: bump to force the QueuePane to re-fetch after a new run
  // starts.
  const [queueRefreshTrigger, setQueueRefreshTrigger] = useState<number>(0)
  const setActiveProject = (p: string | null) => {
    setActiveProjectRaw(p)
    if (typeof window !== 'undefined' && typeof window.localStorage !== 'undefined') {
      try {
        if (p) window.localStorage.setItem('smolcode.activeProject.v1', p)
        else window.localStorage.removeItem('smolcode.activeProject.v1')
      } catch {
        // ignore
      }
    }
  }
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [projectRefreshTrigger, setProjectRefreshTrigger] = useState<number>(0)
  // Phase 3 F3 (decision 0036): cached project list so the Inspector
  // can render the "files landed outside the project root" notice
  // without re-fetching on every render. Refreshed alongside the
  // project switcher so create / rename events invalidate it.
  const [projects, setProjects] = useState<ProjectInfo[]>([])
  const refreshProjects = useCallback(async () => {
    try {
      const r = await listProjects()
      setProjects(r.projects || [])
    } catch {
      // best-effort: a stale list is harmless
    }
  }, [])
  useEffect(() => {
    void refreshProjects()
  }, [refreshProjects, projectRefreshTrigger])

  // v1.9.x (FE-8): Dashboard overlay open/close.
  const [dashboardOpen, setDashboardOpen] = useState<boolean>(false)
  // v1.9.x (FE-6 / B10): track which run has auto-approve active
  // client-side so the AutoApproveBanner can show. We use a Set keyed
  // by runId so a rerun/retry on the same id resets cleanly when
  // activeRunId changes.
  const [autoApproveRunIds, setAutoApproveRunIds] = useState<Set<string>>(
    () => new Set<string>(),
  )

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

  const isMobile = useMediaQuery('(max-width: 900px)')

  const refreshUploads = useCallback(async () => {
    try {
      const r = await listUploads(activeProject)
      setUploads(r.uploads)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [activeProject])

  const refreshRuns = useCallback(async () => {
    try {
      const r = await listRuns()
      setRuns(r.runs)
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

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const r = await listProviders()
        if (cancelled) return
        setProviders(r.providers)
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
        if (!cancelled) {
          setProviders([])
        }
        setError((e as Error).message)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!selectedProviderId) {
      setStoredKeyValue(null)
      return
    }
    setStoredKeyValue(getKey(selectedProviderId))
  }, [selectedProviderId])

  useEffect(() => {
    const id = window.setInterval(() => {
      void refreshRuns()
    }, 5000)
    return () => window.clearInterval(id)
  }, [refreshRuns])

  useEffect(() => {
    void refreshUploads()
    setProjectRefreshTrigger((n) => n + 1)
  }, [activeProject, refreshUploads])

  // v1.9.x (FE-8): mount the Phase-3 keyboard router on app startup.
  // Handlers wire the global shortcuts (Cmd/Ctrl+Enter submit, Cmd/Ctrl+.
  // stop, Cmd/Ctrl+K palette, Cmd/Ctrl+/ help) to actual UI actions.
  // The submit handler clicks the first non-disabled composer submit
  // button; the stop handler POSTs /api/runs/{id}/stop directly.
  // palette + help open the Dashboard modal in v1.9.x (full palette UI
  // is a future feature).
  useEffect(() => {
    return installKeyboardRouter({
      submit: () => {
        const btn = document.querySelector<HTMLButtonElement>(
          '.plan-task .btn-primary:not([disabled])',
        )
        btn?.click()
      },
      stop: () => {
        // Read the ref so we always use the latest activeRunId, not the
        // one captured when the router was installed (decision 0033).
        const id = activeRunIdRef.current
        if (id) {
          void postStop(id).catch(() => {
            /* surfaced via the stream */
          })
        }
      },
      palette: () => {
        setDashboardOpen(true)
      },
      help: () => {
        setDashboardOpen(true)
      },
    })
    // No deps: the stop handler reads activeRunId via the ref (decision
    // 0033) so re-installing on every activeRunId change is wasted work.
  }, [])

  const selectedProvider: ProviderInfo | null = useMemo(() => {
    if (!selectedProviderId) return null
    return providers.find((p) => p.id === selectedProviderId) ?? null
  }, [providers, selectedProviderId])

  const handleProviderChange = (providerId: string, defaultModel: string) => {
    setSelectedProviderId(providerId)
    setSelectedModel(defaultModel)
    saveLast(providerId, defaultModel)
  }

  const handleKeyChange = (_providerId: string, value: string | null) => {
    setStoredKeyValue(value)
  }

  const onSubmitted = (runId: string) => {
    setActiveRunId(runId)
    setActiveRun(null)
    void refreshRuns()
    setQueueRefreshTrigger((n) => n + 1)
  }

  // Phase 3 F3 (decision 0036, Q3): invoked when the user clicks
  // [Open] next to the Working root row in the Inspector. Calls
  // /api/open-path with the active run id so the BE can resolve
  // the whitelist base from run.effective_cwd (rather than the
  // default workspace). Failure surfaces as a transient error
  // banner -- a 403 here means the path escaped the run's
  // effective_cwd between the snapshot and the click, which is
  // an honest race we surface instead of silently failing.
  const onOpenPath = async (path: string) => {
    try {
      await postOpenPath(path, activeRunId)
    } catch (e) {
      setError('Open failed: ' + (e as Error).message)
    }
  }

  // Phase 3 F3 (decision 0036): branch on kind. outside_root events
  // carry absoluteTarget / effectiveCwd / allowedActions hints for
  // the Q2 modal. Backward-compat: callers that omit kind/default
  // to destructive still work.
  const onApprovalRequest = (
    decisionId: string,
    tool: string,
    args: unknown,
    summary: string,
    kind?: string,
    absoluteTarget?: string | null,
    effectiveCwd?: string | null,
    allowedActions?: string[] | null,
  ) => {
    if (kind === 'outside_root') {
      setPending({
        decisionId,
        tool,
        args,
        summary,
        kind: 'outside_root',
        absoluteTarget: absoluteTarget ?? undefined,
        effectiveCwd: effectiveCwd ?? undefined,
        allowedActions: allowedActions ?? undefined,
      })
      return
    }
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

  // v1.9.x (FE-6 / B10) + decision 0027: ApprovalModal reports
  // auto-approve flips; the FE clears/sets the client-side flag AND
  // POSTs to /api/runs/{id}/auto-approve so the BE's destructive gate
  // sees the same state on the next tool call. We best-effort the
  // POST: a stale run id (run already ended) returns 404/409, which
  // we silently swallow since the client-side state is the source
  // of truth for the banner. The next page reload will resync via
  // the session's actual flag.
  const onAutoApproveToggle = (active: boolean) => {
    if (!activeRunId) return
    setAutoApproveRunIds((prev) => {
      const next = new Set(prev)
      if (active) next.add(activeRunId)
      else next.delete(activeRunId)
      return next
    })
    void postAutoApprove(activeRunId, active).catch(() => {
      /* surfaced via the stream on the next destructive prompt */
    })
  }

  // v1.9.x (FE-6): banner Disable also clears the flag (delegates to
  // the toggle above so the BE POST happens through one code path).
  const onAutoApproveDisable = () => {
    onAutoApproveToggle(false)
  }

  // v1.9.x (FE-6): clear flag when active run changes (rerun / retry /
  // new run). Otherwise stale flag from a previous run would persist.
  useEffect(() => {
    if (activeRun && (activeRun.status === 'done' || activeRun.status === 'error' || activeRun.status === 'stopped')) {
      setAutoApproveRunIds((prev) => {
        if (!prev.has(activeRun.id)) return prev
        const next = new Set(prev)
        next.delete(activeRun.id)
        return next
      })
    }
  }, [activeRun?.id, activeRun?.status])

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
          style={{ display: isMobile ? 'inline-flex' : 'none' }}
          onClick={() => setInspectorOpen((v) => !v)}
        >
          {inspectorOpen ? 'Inspector ▴' : 'Inspector ▾'}
        </button>
        {/* v1.9.x (FE-8): Dashboard launcher */}
        <button
          type="button"
          className="btn btn-secondary dashboard-open"
          aria-expanded={dashboardOpen}
          aria-controls="dashboard-overlay"
          onClick={() => setDashboardOpen((v) => !v)}
        >
          {dashboardOpen ? 'Dashboard ▴' : 'Dashboard ▾'}
        </button>
        <div className="ws" title={config.workspace}>
          {config.workspace.split(/[\\/]/).slice(-2).join('/')}
        </div>
        <ProjectSwitcher
          value={activeProject}
          onChange={setActiveProject}
          refreshTrigger={projectRefreshTrigger}
          workspace={config?.workspace ?? ''}
        />
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
              sessionId={activeSessionId}
              project={activeProject}
              onSubmitted={onSubmitted}
            />
          </section>

          <section className="plan-queue">
            <h3>Active & queue</h3>
            <QueuePane
              refreshTrigger={queueRefreshTrigger}
              activeRunId={activeRunId}
              onSelectActive={(id) => setActiveRunId(id)}
            />
          </section>

          <section className="plan-sessions">
            <h3>Sessions</h3>
            <SessionsPane
              project={activeProject}
              activeSessionId={activeSessionId}
              onSelect={setActiveSessionId}
              refreshTrigger={projectRefreshTrigger}
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
            {/* v1.9.x (FE-7): in-flight StopButton OR terminal RunActions */}
            {activeRunId && !runTerminal && <StopButton runId={activeRunId} onStopped={() => void refreshRuns()} />}
            {activeRunId && runTerminal && (
              <RunActions
                runId={activeRunId}
                onRestart={(resp) => onSubmitted(resp.run_id)}
              />
            )}
          </div>
          {/* v1.9.x (FE-6): mid-run banner above the event stream */}
          {activeRunId && autoApproveRunIds.has(activeRunId) && (
            <AutoApproveBanner runId={activeRunId} onDisable={onAutoApproveDisable} />
          )}
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
          style={{ display: isMobile && !inspectorOpen ? 'none' : 'block' }}
        >
          <h3>Inspector</h3>
          <Inspector
            activeRun={activeRun}
            config={config}
            treeRefreshTrigger={treeRefreshTrigger}
            project={activeProject}
            projectInfo={projects.find((p) => p.name === activeProject) || null}
            onFileClick={(p) => setFilePreviewPath(p)}
            onOpenPath={onOpenPath}
          />
        </aside>
      </div>

      {filePreviewPath && (
        <FilePreview
          path={filePreviewPath}
          project={activeProject}
          onClose={() => setFilePreviewPath(null)}
        />
      )}

      <ApprovalModal
        pending={pending}
        onDecide={onDecide}
        onAutoApproveToggle={onAutoApproveToggle}
      />

      {/* v1.9.x (FE-8): Dashboard modal overlay */}
      {dashboardOpen && (
        <div
          id="dashboard-overlay"
          className="dashboard-overlay"
          role="dialog"
          aria-modal="true"
          aria-label="Dashboard"
        >
          <div className="dashboard-overlay-card">
            <div className="dashboard-overlay-head">
              <h2>Dashboard</h2>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setDashboardOpen(false)}
              >
                Close
              </button>
            </div>
            <Dashboard />
            {/* decision 0032: per-provider usage caps */}
            <UsageLimitsPanel />
          </div>
        </div>
      )}
    </div>
  )
}

export default App
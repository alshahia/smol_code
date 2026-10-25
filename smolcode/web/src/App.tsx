// smolcode Workbench: a run-first shell.
//
// The run is the unit of work. A 72px rail holds every run; the stage
// belongs to one run at a time; the composer stays docked so the next task
// is always one keystroke away. Everything that used to be a permanent
// pane (runs, queue, sessions, audit, context, usage) opens as a deliberate
// sheet or drawer, leaving the trace the room it needs.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Icon, IconSprite } from './components/workbench/Icon'
import type { PendingApproval } from './components/ApprovalModal'
import { Sheet } from './components/workbench/Sheet'
import { TraceView } from './components/workbench/TraceView'
import { ChangesView } from './components/workbench/ChangesView'
import { ConsoleView } from './components/workbench/ConsoleView'
import { FilesView } from './components/workbench/FilesView'
import { ApprovalGate } from './components/workbench/ApprovalGate'
import { RunsPanel } from './components/workbench/RunsPanel'
import { ContextPanel } from './components/workbench/ContextPanel'
import { CommandPalette, type PaletteAction } from './components/workbench/CommandPalette'
import { RunComposer } from './components/RunComposer'
import { FileMentionInput } from './components/FileMentionInput'
import { StopButton } from './components/StopButton'
import { PauseButton } from './components/PauseButton'
import { RunActions } from './components/RunActions'
import { AutoApproveBanner } from './components/AutoApproveBanner'
import { QueuePane } from './components/QueuePane'
import { SessionsPane } from './components/SessionsPane'
import { AuditPanel } from './components/AuditPanel'
import { Dashboard } from './components/Dashboard'
import { UsageLimitsPanel } from './components/UsageLimitsPanel'
import { FilePreview } from './components/FilePreview'
import { installKeyboardRouter } from './lib/keyboard'
import { loadLast, saveLast } from './lib/lastSelection'
import { useRunStream } from './hooks/useRunStream'
import {
  getConfig,
  listProviders,
  listRuns,
  listUploads,
  postApproval,
  postAutoApprove,
  postOpenPath,
  postStop,
  startRun,
  type ConfigResponse,
  type ProviderInfo,
  type UploadMetadata,
  type RunSummary,
} from './api'
import { getKey } from './lib/keysStore'

type ViewName = 'trace' | 'changes' | 'console' | 'files'
type SheetName = 'runs' | 'launch' | 'queue' | 'sessions' | 'audit' | 'context' | 'usage' | 'help'

const TERMINAL = new Set(['done', 'error', 'stopped'])
// Mac gets the glyph it knows; everything else gets Ctrl. This is used only
// for visible key hints, never for dispatch (the router decides that).
const MOD =
  typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
    ? '⌘'
    : 'Ctrl'

function App() {
  const [config, setConfig] = useState<ConfigResponse | null>(null)
  const [uploads, setUploads] = useState<UploadMetadata[]>([])
  const [tier, setTier] = useState<string>('restricted')
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const activeRunIdRef = useRef<string | null>(null)
  useEffect(() => {
    activeRunIdRef.current = activeRunId
  }, [activeRunId])

  const [activeRun, setActiveRun] = useState<RunSummary | null>(null)
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [pending, setPending] = useState<PendingApproval | null>(null)
  const [lastDiff, setLastDiff] = useState<PendingApproval | null>(null)
  const [editedAfter, setEditedAfter] = useState<string | null>(null)

  const [fatalError, setFatalError] = useState<string | null>(null)
  const [transientError, setTransientError] = useState<string | null>(null)
  const [treeRefreshTrigger, setTreeRefreshTrigger] = useState<number>(0)

  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(null)
  const [selectedModel, setSelectedModel] = useState<string>('')
  const [storedKeyValue, setStoredKeyValue] = useState<string | null>(null)

  const [activeProject, setActiveProjectRaw] = useState<string | null>(() => {
    if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') return null
    try {
      return window.localStorage.getItem('smolcode.activeProject.v1') || null
    } catch {
      return null
    }
  })
  const setActiveProject = (next: string | null) => {
    setActiveProjectRaw(next)
    if (typeof window !== 'undefined' && typeof window.localStorage !== 'undefined') {
      try {
        if (next) window.localStorage.setItem('smolcode.activeProject.v1', next)
        else window.localStorage.removeItem('smolcode.activeProject.v1')
      } catch {
        // ignore
      }
    }
  }

  const [filePreviewPath, setFilePreviewPath] = useState<string | null>(null)
  const [queueRefreshTrigger, setQueueRefreshTrigger] = useState<number>(0)
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [projectRefreshTrigger, setProjectRefreshTrigger] = useState<number>(0)
  const [autoApproveRunIds, setAutoApproveRunIds] = useState<Set<string>>(() => new Set<string>())

  const [view, setView] = useState<ViewName>('trace')
  const [sheet, setSheet] = useState<SheetName | null>(null)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [dockTask, setDockTask] = useState('')
  const [dockAnchor, setDockAnchor] = useState(false)
  const [dockError, setDockError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  const refreshUploads = useCallback(async () => {
    try {
      const result = await listUploads(activeProject)
      setUploads(result.uploads)
      setTransientError(null)
    } catch (error) {
      setTransientError((error as Error).message)
    }
  }, [activeProject])

  const refreshRuns = useCallback(async () => {
    try {
      const result = await listRuns()
      setRuns(result.runs)
      setActiveRun(result.runs.find((run) => run.id === activeRunId) ?? null)
    } catch {
      // background poll: the stream owns the visible failure
    }
  }, [activeRunId])

  const bootstrappedRef = useRef(false)
  useEffect(() => {
    if (bootstrappedRef.current) return
    bootstrappedRef.current = true
    void (async () => {
      try {
        const nextConfig = await getConfig()
        setConfig(nextConfig)
        const last = loadLast()
        const restoredProvider = nextConfig.provider
        const restoredModel =
          last && last.providerId === nextConfig.provider && last.model.length > 0
            ? last.model
            : nextConfig.model
        setSelectedProviderId(restoredProvider)
        setSelectedModel(restoredModel)
        await refreshUploads()
        await refreshRuns()
      } catch (error) {
        setFatalError((error as Error).message)
      }
    })()
  }, [refreshUploads, refreshRuns])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const result = await listProviders()
        if (cancelled) return
        setProviders(result.providers)
        const last = loadLast()
        if (last && last.providerId.length > 0) {
          const info = result.providers.find((provider) => provider.id === last.providerId)
          if (info) {
            setSelectedProviderId(info.id)
            setSelectedModel(last.model.length > 0 ? last.model : info.default_model)
          }
        }
      } catch (error) {
        if (!cancelled) setProviders([])
        setTransientError((error as Error).message)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const [lastKeyProviderId, setLastKeyProviderId] = useState(selectedProviderId)
  if (selectedProviderId !== lastKeyProviderId) {
    setLastKeyProviderId(selectedProviderId)
    setStoredKeyValue(selectedProviderId ? getKey(selectedProviderId) : null)
  }

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const result = await listRuns()
        if (cancelled) return
        setRuns(result.runs)
        setActiveRun(result.runs.find((run) => run.id === activeRunId) ?? null)
      } catch {
        // poll owns retry
      }
    })()
    return () => {
      cancelled = true
    }
    // refreshRuns changes exactly when activeRunId does; that is the trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshRuns])

  useEffect(() => {
    const id = window.setInterval(() => void refreshRuns(), 5000)
    return () => window.clearInterval(id)
  }, [refreshRuns])

  useEffect(() => {
    void refreshUploads()
    setProjectRefreshTrigger((value) => value + 1)
  }, [activeProject, refreshUploads])

  useEffect(() => {
    if (!toast) return
    const id = window.setTimeout(() => setToast(null), 2600)
    return () => window.clearTimeout(id)
  }, [toast])

  const selectedProvider: ProviderInfo | null = useMemo(() => {
    if (!selectedProviderId) return null
    return providers.find((provider) => provider.id === selectedProviderId) ?? null
  }, [providers, selectedProviderId])

  const handleProviderChange = (providerId: string, defaultModel: string) => {
    setSelectedProviderId(providerId)
    setSelectedModel(defaultModel)
    saveLast(providerId, defaultModel)
  }

  const handleKeyChange = (_providerId: string, value: string | null) => {
    setStoredKeyValue(value)
  }

  const openSheet = (next: SheetName) => {
    setPaletteOpen(false)
    setSheet(next)
  }

  const openPalette = () => {
    setSheet(null)
    setPaletteOpen(true)
  }

  const copyText = async (text: string, label: string) => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable')
      await navigator.clipboard.writeText(text)
      setToast(label)
    } catch {
      setToast('Could not copy to the clipboard')
    }
  }

  const onSubmitted = (runId: string) => {
    setActiveRunId(runId)
    setActiveRun(null)
    setPending(null)
    setEditedAfter(null)
    setLastDiff(null)
    setView('trace')
    setSheet(null)
    setDockError(null)
    void refreshRuns()
    setQueueRefreshTrigger((value) => value + 1)
  }

  const onOpenPath = async (path: string) => {
    try {
      await postOpenPath(path, activeRunId)
    } catch (error) {
      setTransientError('Open failed: ' + (error as Error).message)
    }
  }

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
    setEditedAfter(null)
    setView('changes')
    setSheet(null)
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
    const next: PendingApproval = {
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
      stats: stats && typeof stats === 'object' ? (stats as PendingApproval['stats']) : undefined,
    }
    setEditedAfter(null)
    setPending(next)
    setLastDiff(next)
    setView('changes')
    setSheet(null)
    setTreeRefreshTrigger((value) => value + 1)
    void refreshRuns()
  }

  const onFinal = (_result: string | null, _error: string | null) => {
    void refreshRuns()
  }

  const { events, rows, connection } = useRunStream({
    runId: activeRunId,
    status: activeRun?.status ?? null,
    onApprovalRequest,
    onDiffProposed,
    onFinal,
  })

  const onDecide = async (approved: boolean, reason: string, edited: string | null) => {
    if (!pending || !activeRunId) return
    const decisionId = pending.decisionId
    setPending(null)
    setEditedAfter(null)
    try {
      await postApproval(activeRunId, decisionId, approved, reason, edited)
      setToast(approved ? 'Released · decision appended to audit' : 'Denied · run stays paused')
      void refreshRuns()
    } catch (error) {
      setTransientError((error as Error).message)
    }
  }

  const onAutoApproveToggle = (active: boolean) => {
    if (!activeRunId) return
    setAutoApproveRunIds((previous) => {
      const next = new Set(previous)
      if (active) next.add(activeRunId)
      else next.delete(activeRunId)
      return next
    })
    void postAutoApprove(activeRunId, active).catch(() => {
      // the next prompt surfaces a failed flip honestly
    })
  }

  const onAutoApprove = () => {
    void onDecide(true, 'auto-approve', editedAfter)
    onAutoApproveToggle(true)
  }

  const activeRunIsTerminal = activeRun !== null && TERMINAL.has(activeRun.status)
  const [lastAutoApproveKey, setLastAutoApproveKey] = useState<string | null>(null)
  const autoApproveKey = activeRun ? activeRun.id + ':' + activeRun.status : null
  if (autoApproveKey !== lastAutoApproveKey) {
    setLastAutoApproveKey(autoApproveKey)
    if (activeRun && activeRunIsTerminal) {
      setAutoApproveRunIds((previous) => {
        if (!previous.has(activeRun.id)) return previous
        const next = new Set(previous)
        next.delete(activeRun.id)
        return next
      })
    }
  }

  useEffect(() => {
    return installKeyboardRouter({
      submit: () => {
        const sheetButton = document.querySelector<HTMLButtonElement>(
          '[data-run-submit]:not([disabled])',
        )
        const dockButton = document.querySelector<HTMLButtonElement>(
          '[data-composer-submit]:not([disabled])',
        )
        ;(sheetButton ?? dockButton)?.click()
      },
      stop: () => {
        const id = activeRunIdRef.current
        if (id) void postStop(id).catch(() => undefined)
      },
      palette: openPalette,
      help: () => openSheet('help'),
    })
  }, [])

  const startDockRun = async () => {
    const task = dockTask.trim()
    if (!task) {
      setDockError('Write a task first.')
      return
    }
    setStarting(true)
    setDockError(null)
    try {
      const env = selectedProvider?.env_vars[0] ?? null
      const keys =
        env && storedKeyValue && storedKeyValue.length > 0
          ? { [env]: storedKeyValue }
          : undefined
      const response = await startRun(task, tier, {
        provider: selectedProviderId ?? undefined,
        model: selectedModel || undefined,
        keys,
        session_id: activeSessionId,
        project: activeProject,
        anchor_to_project_root: dockAnchor || undefined,
      })
      setDockTask('')
      onSubmitted(response.run_id)
    } catch (error) {
      setDockError((error as Error).message)
    } finally {
      setStarting(false)
    }
  }

  if (fatalError) {
    return (
      <div className="error-screen">
        <h1>Cannot reach the smolcode web server</h1>
        <pre>{fatalError}</pre>
        <p>
          Is <code>smolcode web</code> running on <code>http://127.0.0.1:7860</code>?
        </p>
      </div>
    )
  }

  if (!config) {
    return <div className="loading">Loading...</div>
  }

  const needsCount = runs.filter((run) => run.has_pending_approval || run.status === 'awaiting_approval').length
  const queuedCount = runs.filter((run) => run.status === 'queued').length
  const activeStatus = activeRun?.status ?? (activeRunId ? 'pending' : '')
  const terminal = activeRun !== null && TERMINAL.has(activeRun.status)
  const pendingCount = pending ? 1 : 0
  const stageProject = activeRun?.project || activeProject || 'workspace'
  const workspaceLabel = config.workspace.split(/[\\/]/).slice(-2).join('/')

  const tabs: { id: ViewName; label: string; count?: number; alert?: boolean }[] = [
    { id: 'trace', label: 'Trace', count: events.length || undefined },
    { id: 'changes', label: 'Changes', count: pendingCount || (lastDiff ? 1 : undefined), alert: pendingCount > 0 },
    { id: 'console', label: 'Console' },
    { id: 'files', label: 'Files' },
  ]

  const paletteActions: PaletteAction[] = [
    { id: 'new-run', label: 'Start a new run', hint: 'New run sheet', run: () => openSheet('launch') },
    { id: 'runs', label: 'Open runs', hint: 'All runs', run: () => openSheet('runs') },
    { id: 'queue', label: 'Open queue', hint: queuedCount + ' queued', run: () => openSheet('queue') },
    { id: 'sessions', label: 'Open sessions', hint: activeSessionId ? activeSessionId.slice(0, 8) : 'none attached', run: () => openSheet('sessions') },
    { id: 'audit', label: 'Open audit chain', hint: 'append-only', run: () => openSheet('audit') },
    { id: 'context', label: 'Open context', hint: 'provider, policy, uploads', run: () => openSheet('context') },
    { id: 'usage', label: 'Open usage', hint: 'dashboard + caps', run: () => openSheet('usage') },
    { id: 'help', label: 'Open help', hint: 'shortcuts', shortcut: '?', run: () => openSheet('help') },
  ]
  if (activeRunId) {
    paletteActions.unshift(
      { id: 'trace', label: 'Go to trace', hint: activeRunId, run: () => setView('trace') },
      { id: 'changes', label: 'Go to changes', hint: pendingCount ? 'gate waiting' : 'review', run: () => setView('changes') },
      { id: 'console', label: 'Go to console', hint: 'raw events', run: () => setView('console') },
      { id: 'files', label: 'Go to files', hint: 'workspace', run: () => setView('files') },
    )
  }

  return (
    <div className="app">
      <IconSprite />

      {transientError && (
        <div className="error-banner app-transient-error" role="alert">
          <span>{transientError}</span>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => {
              void refreshUploads()
              void refreshRuns()
            }}
          >
            Retry
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            aria-label="Dismiss error"
            onClick={() => setTransientError(null)}
          >
            Dismiss
          </button>
        </div>
      )}

      <header className="topbar">
        <div className="brand">
          <b>smolcode</b>
          <small>workbench</small>
        </div>
        <button
          type="button"
          className="project-btn"
          onClick={() => openSheet('context')}
          aria-label="Project and workspace context"
        >
          <Icon name="folder" size={14} />
          <span className="pname">{activeProject || 'workspace'}</span>
          <span className="path">{workspaceLabel}</span>
          <Icon name="chevron" size={13} />
        </button>
        <span className="daemon">
          <span className="dot" />
          127.0.0.1
          <span className="local-tag">local</span>
        </span>
        <div className="top-actions">
          {needsCount > 0 ? (
            <button type="button" className="needs" onClick={() => openSheet('runs')}>
              <span className="dot" />
              <b>{needsCount}</b> {needsCount === 1 ? 'needs' : 'need'} you
            </button>
          ) : (
            <button type="button" className="needs is-clear" onClick={() => openSheet('runs')}>
              <span className="dot" />
              clear
            </button>
          )}
          <button type="button" className="kbd" onClick={openPalette} aria-label="Open command palette">
            {MOD} K
          </button>
          <button type="button" className="icon-top" onClick={() => openSheet('audit')} aria-label="Open audit chain">
            <Icon name="chain" size={15} />
          </button>
          <button type="button" className="icon-top" onClick={() => openSheet('help')} aria-label="Help">
            <Icon name="help" size={15} />
          </button>
        </div>
      </header>

      <div className="frame">
        <aside className="rail" aria-label="Runs">
          <button type="button" className="rail-menu" onClick={() => openSheet('runs')} aria-label="Open all runs">
            <Icon name="menu" size={17} />
          </button>
          <div className="rail-runs">
            {runs.slice(0, 9).map((run) => (
              <button
                key={run.id}
                type="button"
                className={'run-chip' + (run.id === activeRunId ? ' is-active' : '')}
                data-status={run.status}
                data-tip={run.task}
                aria-label={'Open run ' + run.id}
                aria-pressed={run.id === activeRunId}
                onClick={() => {
                  setActiveRunId(run.id)
                  setView('trace')
                  setSheet(null)
                }}
              >
                <span className="chip-id">{shortId(run.id)}</span>
                <span className="chip-dot" aria-hidden="true" />
                {run.has_pending_approval || run.status === 'awaiting_approval' ? (
                  <span className="rail-alert" aria-hidden="true">!</span>
                ) : null}
                <span className="sr-only">{run.task}</span>
              </button>
            ))}
          </div>
          <div className="rail-sep" />
          <button
            type="button"
            className="rail-tool"
            onClick={() => openSheet('queue')}
            aria-label={'Open queue, ' + queuedCount + ' queued'}
            title="Active and queued runs"
          >
            <Icon name="queue" size={17} />
            {queuedCount > 0 ? <span className="badge">{queuedCount}</span> : null}
          </button>
          <div className="rail-foot">
            <button
              type="button"
              className="rail-tool"
              onClick={() => openSheet('audit')}
              aria-label="Open audit chain"
              title="Append-only audit chain"
            >
              <Icon name="chain" size={17} />
              <span className="chain-count">audit</span>
            </button>
            <button
              type="button"
              className="rail-tool"
              onClick={() => openSheet('help')}
              aria-label="Help and shortcuts"
              title="Help"
            >
              <Icon name="help" size={17} />
            </button>
          </div>
        </aside>

        <main className="stage">
          {activeRunId ? (
            <div className="run-shell">
              <header className="stage-head">
                <div className="stage-crumb">
                  <code>{activeRunId}</code>
                  <span className="slash">/</span>
                  <span>{stageProject}</span>
                  <span className="slash">/</span>
                  <span>{activeRun?.tier || tier}</span>
                  {activeRun?.queue_position != null ? (
                    <>
                      <span className="slash">/</span>
                      <span className="warn">queue #{activeRun.queue_position}</span>
                    </>
                  ) : null}
                </div>
                <h1 className="objective">{activeRun?.task || 'Resolving run…'}</h1>
                <div className="meta-row">
                  <span className={'status-pill ' + activeStatus}>
                    <i aria-hidden="true" />
                    {statusLabel(activeStatus)}
                  </span>
                  <span className="tier-tag">tier · {activeRun?.tier || tier}</span>
                  <span>{activeRun?.model || selectedModel || 'server model'}</span>
                  <span>{runDuration(activeRun)}</span>
                  {activeRun?.tokens?.total != null ? (
                    <span>{activeRun.tokens.total.toLocaleString()} tokens</span>
                  ) : null}
                  {activeRun?.tokens?.cost_usd != null ? (
                    <span>{'$' + activeRun.tokens.cost_usd.toFixed(4)}</span>
                  ) : null}
                </div>
                <div className="stage-actions">
                  {activeRun && (activeRun.status === 'running' || activeRun.status === 'paused' || activeRun.status === 'awaiting_approval') ? (
                    <PauseButton runId={activeRun.id} status={activeRun.status} onChanged={() => void refreshRuns()} />
                  ) : null}
                  {activeRun && !terminal ? (
                    <StopButton runId={activeRun.id} onStopped={() => void refreshRuns()} />
                  ) : null}
                  {activeRun && terminal ? (
                    <RunActions runId={activeRun.id} onRestart={(response) => onSubmitted(response.run_id)} />
                  ) : null}
                  <button
                    type="button"
                    className="icon-top"
                    aria-label="Open run context"
                    onClick={() => openSheet('context')}
                  >
                    <Icon name="dots" size={16} />
                  </button>
                </div>
              </header>

              <div className="stage-modes">
                <div className="stage-tabs" role="tablist" aria-label="Run views">
                  {tabs.map((tab) => (
                    <button
                      key={tab.id}
                      id={'wb-tab-' + tab.id}
                      type="button"
                      role="tab"
                      aria-selected={view === tab.id}
                      aria-controls="wb-stage-panel"
                      className={view === tab.id ? 'on' : ''}
                      onClick={() => setView(tab.id)}
                    >
                    {tab.label}
                      {tab.count != null ? (
                        <span className={'count' + (tab.alert ? ' alert' : '')}>{tab.count}</span>
                      ) : null}
                    </button>
                  ))}
                </div>
                <span className="grow" />
                <button
                  type="button"
                  className="mode-context"
                  onClick={() => openSheet('context')}
                  aria-label="Open context drawer"
                >
                  <Icon name="panel" size={14} /> Context
                </button>
              </div>

              {activeRunId && autoApproveRunIds.has(activeRunId) && (
                <AutoApproveBanner runId={activeRunId} onDisable={() => onAutoApproveToggle(false)} />
              )}

              <div
                className="stage-body"
                id="wb-stage-panel"
                role="tabpanel"
                aria-labelledby={'wb-tab-' + view}
              >
                {!activeRun ? (
                  <div className="run-loading">
                    <span className="mono">{activeRunId}</span>
                    <p>Resolving this run…</p>
                  </div>
                ) : view === 'trace' ? (
                  <TraceView
                    rows={rows}
                    events={events}
                    run={activeRun}
                    pending={pending}
                    connection={connection}
                    onOpenChanges={() => setView('changes')}
                  />
                ) : view === 'changes' ? (
                  <ChangesView
                    pending={pending}
                    lastDiff={lastDiff}
                    editedAfter={editedAfter}
                    onEdit={(next) => setEditedAfter(next)}
                    onOpenFile={(path) => setFilePreviewPath(path)}
                    onCopy={(text, label) => void copyText(text, label)}
                  />
                ) : view === 'console' ? (
                  <ConsoleView
                    events={events}
                    run={activeRun}
                    onCopy={(text, label) => void copyText(text, label)}
                  />
                ) : (
                  <FilesView
                    workspaceRoot={config.workspace}
                    project={activeProject}
                    touchedPaths={activeRun.touched_paths || []}
                    refreshTrigger={treeRefreshTrigger}
                    onFileClick={(path) => setFilePreviewPath(path)}
                    onOpenPath={(path) => void onOpenPath(path)}
                  />
                )}
              </div>

              {pending ? (
                <ApprovalGate
                  pending={pending}
                  editedAfter={editedAfter}
                  onDecide={(approved, reason, edited) => void onDecide(approved, reason, edited)}
                  onAutoApprove={onAutoApprove}
                  onOpenChanges={() => setView('changes')}
                />
              ) : null}
            </div>
          ) : (
            <div className="empty-stage">
              <div className="empty-stage-card">
                <h1>The run is the unit of work.</h1>
                <p>
                  A run carries its own tier, evidence, change, and audit trail. Pick one from the
                  rail, or start the next one below.
                </p>
                <div className="actions">
                  <button type="button" className="btn btn-primary" onClick={() => openSheet('launch')}>
                    <Icon name="play" size={14} /> Start a run
                  </button>
                  <button type="button" className="btn" onClick={() => openSheet('runs')}>
                    <Icon name="menu" size={14} /> Open a run
                  </button>
                </div>
                {runs.length > 0 ? (
                  <div className="recent">
                    <h2>Recent runs</h2>
                    {runs.slice(0, 3).map((run) => (
                      <button
                        key={run.id}
                        type="button"
                        onClick={() => {
                          setActiveRunId(run.id)
                          setView('trace')
                        }}
                      >
                        <code>{run.id}</code>
                        <span>
                          {run.tier} · {statusLabel(run.status)}
                        </span>
                        <Icon name="arrow" size={13} />
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          )}
        </main>
      </div>

      <footer className="composer wb-composer">
        <div className="composer-main">
          <div className="composer-top">
            <span className="composer-label">New run</span>
            <span className="composer-kbd">{MOD}+Enter start · {MOD}+K commands</span>
          </div>
          <div className="composer-inputrow">
            <FileMentionInput
              value={dockTask}
              onChange={setDockTask}
              project={activeProject}
              rows={1}
              placeholder="Describe the task, or @ a file"
              disabled={starting}
            />
            {activeProject ? (
              <label className="checkline composer-anchor" title="Resolve writes against this project root; escapes require the outside-root gate.">
                <input
                  type="checkbox"
                  checked={dockAnchor}
                  onChange={(event) => setDockAnchor(event.target.checked)}
                  disabled={starting}
                />
                Anchor
              </label>
            ) : null}
            <button
              type="button"
              className="composer-run"
              data-composer-submit
              onClick={() => void startDockRun()}
              disabled={starting}
            >
              {starting ? 'Starting…' : 'Run'} <Icon name="arrow" size={13} />
            </button>
          </div>
          {dockError ? <div className="composer-error" role="alert">{dockError}</div> : null}
        </div>
        <div className="composer-side">
          <span className="composer-provider">
            <label className="sr-only" htmlFor="dock-provider">Model provider</label>
            <select
              id="dock-provider"
              aria-label="Model provider"
              value={selectedProviderId ?? ''}
              onChange={(event) => {
                const id = event.target.value
                const info = providers.find((provider) => provider.id === id)
                handleProviderChange(id, info?.default_model || '')
              }}
            >
              {!selectedProviderId ? <option value="">Server default</option> : null}
              {selectedProviderId && !providers.some((provider) => provider.id === selectedProviderId) ? (
                <option value={selectedProviderId}>{selectedProviderId}</option>
              ) : null}
              {providers.map((provider) => (
                <option key={provider.id} value={provider.id}>{provider.name}</option>
              ))}
            </select>
          </span>
          <button
            type="button"
            className="composer-chip"
            onClick={() => openSheet('launch')}
            aria-label={'Tier: ' + tier + '. Open new run'}
          >
            <span className="tier-dot" /> {tier}
          </button>
          <button
            type="button"
            className="composer-chip"
            onClick={() => openSheet('context')}
            aria-label="Model: open context"
          >
            {selectedModel || 'server model'}
          </button>
        </div>
      </footer>

      <Sheet
        open={sheet === 'runs'}
        title="Runs"
        subtitle={needsCount > 0 ? needsCount + (needsCount === 1 ? ' needs' : ' need') + ' you · ' + runs.length + ' total' : runs.length + ' total'}
        variant="side"
        onClose={() => setSheet(null)}
        className="runs-sheet"
      >
        <RunsPanel
          runs={runs}
          activeRunId={activeRunId}
          onSelect={(runId) => {
            setActiveRunId(runId)
            setView('trace')
            setSheet(null)
          }}
          onNewRun={() => openSheet('launch')}
        />
      </Sheet>

      <Sheet
        open={sheet === 'launch'}
        title="New run"
        subtitle="One task. One tier. One auditable run."
        variant="launch"
        onClose={() => setSheet(null)}
      >
        <div className="tier-ladder">
          <h3>Release tier</h3>
          {config.tiers.filter((entry) => entry.name !== 'full_access').map((entry) => (
            <button
              key={entry.name}
              type="button"
              className={'tier-option' + (tier === entry.name ? ' on' : '')}
              onClick={() => setTier(entry.name)}
              aria-pressed={tier === entry.name}
            >
              <span className="radio" aria-hidden="true" />
              <span>
                <span className="tname">{entry.name}</span>
                <span className="tdesc">
                  {tierDescription(entry.name)} {entry.max_steps} steps · {entry.timeout_s}s · {entry.network} network.
                </span>
              </span>
              <span className="tflag">{entry.name === 'restricted' ? 'default' : 'opt-in'}</span>
            </button>
          ))}
        </div>
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
        <div className="launch-foot">
          <span className="launch-cost">
            runs on <b>{selectedProvider?.name || 'server defaults'}</b>
            {selectedModel ? ' · ' + selectedModel : ''}
          </span>
          <button type="button" className="btn launch-context" onClick={() => setSheet('context')}>
            Context
          </button>
        </div>
        <p className="launch-note muted small">
          full_access is not offered from the composer; it requires an explicit CLI decision.
          Every run still executes model-written code in Docker.
        </p>
      </Sheet>

      <Sheet
        open={sheet === 'queue'}
        title="Queue"
        subtitle="Active and waiting runs, FIFO with reordering."
        variant="drawer"
        wide
        onClose={() => setSheet(null)}
      >
        <QueuePane
          refreshTrigger={queueRefreshTrigger}
          activeRunId={activeRunId}
          onSelectActive={(runId) => {
            setActiveRunId(runId)
            setView('trace')
            setSheet(null)
          }}
        />
      </Sheet>

      <Sheet
        open={sheet === 'sessions'}
        title="Sessions"
        subtitle={activeProject ? 'Project · ' + activeProject : 'Workspace-wide'}
        variant="drawer"
        onClose={() => setSheet(null)}
      >
        <SessionsPane
          project={activeProject}
          activeSessionId={activeSessionId}
          onSelect={(sessionId) => {
            setActiveSessionId(sessionId)
            setToast(sessionId ? 'Session attached to new runs' : 'No session attached')
          }}
          refreshTrigger={projectRefreshTrigger}
        />
      </Sheet>

      <Sheet
        open={sheet === 'audit'}
        title="Audit chain"
        subtitle="Append-only. Every decision carries its reason."
        variant="drawer"
        wide
        onClose={() => setSheet(null)}
      >
        <AuditPanel />
      </Sheet>

      <Sheet
        open={sheet === 'context'}
        title="Context"
        subtitle="Run, project, provider, policy and uploads."
        variant="drawer"
        wide
        onClose={() => setSheet(null)}
      >
        <ContextPanel
          config={config}
          activeRun={activeRun}
          activeProject={activeProject}
          activeSessionId={activeSessionId}
          projectsRefreshTrigger={projectRefreshTrigger}
          providers={providers}
          selectedProviderId={selectedProviderId}
          selectedProvider={selectedProvider}
          selectedModel={selectedModel}
          storedKeyValue={storedKeyValue}
          uploads={uploads}
          onProjectChange={setActiveProject}
          onProviderChange={handleProviderChange}
          onModelChange={(model) => {
            setSelectedModel(model)
            if (selectedProviderId) saveLast(selectedProviderId, model)
          }}
          onKeyChange={handleKeyChange}
          onUploaded={() => void refreshUploads()}
          onOpenPath={(path) => void onOpenPath(path)}
          onOpenRuns={() => openSheet('runs')}
          onOpenSessions={() => openSheet('sessions')}
        />
      </Sheet>

      <Sheet
        open={sheet === 'usage'}
        title="Usage"
        subtitle="Today, per provider, and configured caps."
        variant="drawer"
        wide
        onClose={() => setSheet(null)}
      >
        <Dashboard />
        <UsageLimitsPanel />
      </Sheet>

      <Sheet
        open={sheet === 'help'}
        title="Help"
        subtitle="Keyboard first; the pointer is optional."
        variant="drawer"
        onClose={() => setSheet(null)}
      >
        <div className="help-list">
          <div className="help-row"><kbd>{MOD} + Enter</kbd><span>Start the task in the composer.</span></div>
          <div className="help-row"><kbd>{MOD} + K</kbd><span>Command palette: runs, sheets, views.</span></div>
          <div className="help-row"><kbd>{MOD} + .</kbd><span>Stop the active run.</span></div>
          <div className="help-row"><kbd>?</kbd><span>This sheet.</span></div>
          <div className="help-row"><kbd>Esc</kbd><span>Close a sheet or the palette.</span></div>
          <div className="help-row"><kbd>Tab</kbd><span>Every control, including the gate, is reachable.</span></div>
        </div>
        <div className="drawer-section" style={{ marginTop: 16 }}>
          <h3>What the shell believes</h3>
          <p className="help">
            The run is the unit of work. A tier is a blast-radius choice, not a badge. A diff is held
            until a human releases it, and the release is written to an append-only chain. The server
            binds to loopback; nothing here calls a third-party service.
          </p>
        </div>
      </Sheet>

      <CommandPalette
        open={paletteOpen}
        actions={paletteActions}
        runs={runs}
        onClose={() => setPaletteOpen(false)}
        onSelectRun={(runId) => {
          setActiveRunId(runId)
          setView('trace')
          setSheet(null)
        }}
      />

      {filePreviewPath ? (
        <FilePreview
          path={filePreviewPath}
          project={activeProject}
          onClose={() => setFilePreviewPath(null)}
        />
      ) : null}

      {toast ? <div className="toast show" role="status">{toast}</div> : null}
    </div>
  )
}

function shortId(id: string) {
  return id.length > 5 ? id.slice(-4) : id
}

function statusLabel(status: string) {
  if (status === 'awaiting_approval') return 'awaiting you'
  if (status === 'running') return 'running'
  if (status === 'paused') return 'paused'
  if (status === 'queued') return 'queued'
  if (status === 'done') return 'verified'
  if (status === 'error') return 'error'
  if (status === 'stopped') return 'stopped'
  return status || 'pending'
}

function runDuration(run: RunSummary | null) {
  if (!run) return '—'
  if (run.duration_s != null) return formatSeconds(run.duration_s)
  if (run.started_at && !run.ended_at) {
    return formatSeconds(Math.max(0, Date.now() / 1000 - run.started_at))
  }
  return '—'
}

function formatSeconds(seconds: number) {
  if (seconds < 60) return seconds.toFixed(1) + 's'
  const mins = Math.floor(seconds / 60)
  return mins + 'm ' + Math.round(seconds % 60) + 's'
}

function tierDescription(name: string) {
  if (name === 'restricted') return 'Workspace only. The safe default.'
  if (name === 'elevated') return 'More commands and paths. Opt-in.'
  if (name === 'full_access') return 'Broad access. Only by an explicit CLI decision.'
  return 'Configured tier.'
}

export default App

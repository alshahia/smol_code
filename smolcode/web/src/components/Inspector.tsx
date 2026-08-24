// Inspector: the right-pane of the SPA (decision 0025, Phase 0 FE-1).
//
// Extracted from App.tsx in Phase 0 so the right pane can grow without
// bloating App.tsx. Renders:
//   - Active run summary (id, status, tier, duration, error)
//   - Token usage (input/output/total + step count)
//   - Wall-clock countdown (1s tick) when the run is in flight
//   - Sub-agent hint (when the orchestrator is delegating)
//   - Workspace tree (touched paths highlighted)
//   - Tier policy cards
//   - Recent audit
//
// Props mirror the fields the App used to read directly. The countdown
// ticks once per second locally (no SSE needed) -- the SPA only re-
// hydrates from the server when the run summary changes (e.g. when
// refreshRuns() returns).

import { useEffect, useState } from 'react'
import { TierBadge } from './TierBadge'
import { WorkspaceTree } from './WorkspaceTree'
import { AuditPanel } from './AuditPanel'
import type { ConfigResponse, RunSummary } from '../api'

interface Props {
  activeRun: RunSummary | null
  config: ConfigResponse
  // Phase 0 (decision 0025, B11): bumped by the parent on each
  // diff.proposed / diff.resolved event so the WorkspaceTree refreshes
  // immediately instead of waiting for the 10s poll.
  treeRefreshTrigger?: number
  // Phase 1 (decision 0025 §6.3): scope the workspace tree to the
  // active project (null = legacy workspace).
  project?: string | null
}

const MAX_RUN_WALL_S_FALLBACK = 900 // SMOLCODE_WEB_RUN_TIMEOUT_S default (decision 0023)

function formatHMS(totalSeconds: number): string {
  const sign = totalSeconds < 0 ? '-' : ''
  const t = Math.abs(Math.round(totalSeconds))
  const m = Math.floor(t / 60)
  const s = t % 60
  return sign + m.toString().padStart(2, '0') + ':' + s.toString().padStart(2, '0')
}

export function Inspector({ activeRun, config, treeRefreshTrigger, project }: Props) {
  // 1s tick for the countdown. We start at 0 and only flip to active
  // when the run is in flight; this avoids spurious re-renders for
  // terminal runs.
  const [nowTick, setNowTick] = useState<number>(0)
  const inFlight =
    activeRun !== null &&
    (activeRun.status === 'running' || activeRun.status === 'awaiting_approval')
  useEffect(() => {
    if (!inFlight) {
      return undefined
    }
    const id = window.setInterval(() => {
      setNowTick((n) => n + 1)
    }, 1000)
    return () => window.clearInterval(id)
  }, [inFlight, activeRun?.id])

  // Compute the displayed remaining seconds locally so the value updates
  // every tick without round-tripping to the server. The server value
  // is the authoritative starting point on each refreshRuns() call; we
  // tick it down locally by the nowTick counter (1Hz from useEffect).
  // No Date.now() in the render body -- that would be an impure read.
  const remainingServer = activeRun?.remaining_s ?? null
  const remainingDisplay: number | null = (() => {
    if (remainingServer === null || remainingServer === undefined) return null
    if (!inFlight) return remainingServer
    return Math.max(-60, remainingServer - nowTick)
  })()

  const isTerminal =
    activeRun !== null &&
    (activeRun.status === 'done' ||
      activeRun.status === 'error' ||
      activeRun.status === 'stopped')

  const tokens = activeRun?.tokens
  const stepCount = activeRun?.step_count ?? 0
  const sub = activeRun?.subagent ?? null

  return (
    <>
      {activeRun && (
        <div className="inspector-section">
          <h4>Active run</h4>
          <div className="kv">
            <span>id:</span> <code>{activeRun.id.slice(0, 12)}</code>
          </div>
          <div className="kv">
            <span>status:</span> <code>{activeRun.status}</code>
          </div>
          <div className="kv">
            <span>tier:</span> <code>{activeRun.tier}</code>
          </div>
          {activeRun.duration_s !== null && (
            <div className="kv">
              <span>duration:</span> <code>{activeRun.duration_s.toFixed(1)}s</code>
            </div>
          )}
          {activeRun.error && <div className="error-banner">{activeRun.error}</div>}
        </div>
      )}

      {activeRun && (
        <div className="inspector-section">
          <h4>Token usage</h4>
          {tokens ? (
            <>
              <div className="kv">
                <span>input:</span> <code>{tokens.input.toLocaleString()}</code>
              </div>
              <div className="kv">
                <span>output:</span> <code>{tokens.output.toLocaleString()}</code>
              </div>
              <div className="kv">
                <span>total:</span> <code>{tokens.total.toLocaleString()}</code>
              </div>
              <div className="kv">
                <span>steps:</span> <code>{stepCount}</code>
              </div>
            </>
          ) : (
            <div className="muted small">No token data yet (pre-v1.8 server?).</div>
          )}
        </div>
      )}

      {activeRun && (
        <div className="inspector-section">
          <h4>Wall-clock budget</h4>
          {remainingDisplay === null ? (
            <div className="muted small">No timeout reported.</div>
          ) : inFlight ? (
            remainingDisplay <= 0 ? (
              <div className="warn-banner">
                Run timed out after {formatHMS(MAX_RUN_WALL_S_FALLBACK)} -- the runner is
                forcibly stopping the executor.
              </div>
            ) : (
              <div className="kv">
                <span>remaining:</span> <code>{formatHMS(remainingDisplay)}</code>
                <span className="muted small"> (budget {formatHMS(MAX_RUN_WALL_S_FALLBACK)})</span>
              </div>
            )
          ) : isTerminal ? (
            <div className="muted small">Run is terminal -- no live countdown.</div>
          ) : null}
        </div>
      )}

      {activeRun && sub && (
        <div className="inspector-section">
          <h4>Sub-agent</h4>
          <div className="kv">
            <span>tier:</span> <code>{sub.tier}</code>
          </div>
          <div className="kv">
            <span>id:</span> <code>{sub.id.slice(0, 12)}</code>
          </div>
          {sub.ended_at === null ? (
            <div className="muted small">in flight</div>
          ) : (
            <div className="muted small">
              ended {(sub.ended_at - sub.started_at).toFixed(1)}s after start
            </div>
          )}
        </div>
      )}

      <div className="inspector-section">
        <h4>Workspace</h4>
        <div className="kv">
          <span>Path:</span> <code>{config.workspace}</code>
        </div>
        <div className="kv">
          <span>Executor:</span> <code>{config.executor}</code>
        </div>
        <div className="kv">
          <span>Uploads:</span> <code>{config.uploads_dir}</code>
        </div>
        <div className="kv">
          <span>Max size:</span>{' '}
          <code>{(config.upload_max_bytes / 1024 / 1024).toFixed(0)} MB</code>
        </div>
        <WorkspaceTree
          workspaceRoot={config.workspace}
          touchedPaths={activeRun?.touched_paths}
          refreshTrigger={treeRefreshTrigger}
          project={project}
        />
      </div>

      <div className="inspector-section">
        <h4>Tiers</h4>
        {config.tiers.map((t) => (
          <div key={t.name} className="tier-card">
            <div className="tier-card-head">
              <TierBadge tier={t.name} />
              <span className="muted">uploads={t.uploads}</span>
            </div>
            <div className="muted small">
              cmds: {t.commands.slice(0, 6).join(', ')}
              {t.commands.length > 6 ? ', ...' : ''}
            </div>
          </div>
        ))}
      </div>

      <div className="inspector-section">
        <h4>Recent audit</h4>
        <AuditPanel limit={25} pollIntervalMs={5000} />
      </div>
    </>
  )
}

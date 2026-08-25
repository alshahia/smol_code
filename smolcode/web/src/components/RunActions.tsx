// v1.9.x (decision 0025 sec 3.4 / 3.5 / 3.7 / B4 / B5 / B7): terminal-run
// action cluster. Rendered in the stream header next to / instead of
// the Stop button when the active run is in a terminal state.
//
// Buttons:
//   Retry       -- re-submits the same task via POST /api/runs/{id}/retry.
//   Re-run      -- starts a fresh run with the original task via /rerun.
//   Export      -- downloads the run as run-<id>.json via /export +
//                  downloadExport (creates an object URL + Blob).

import React, { useState } from 'react'
import { retryRun, rerunRun, exportRun, downloadExport, type RunStartResponse } from '../api'

export interface RunActionsProps {
  runId: string
  /** Optional callback after a successful Retry / Re-run so the parent can refresh. */
  onRestart?: (resp: RunStartResponse) => void
}

export function RunActions({ runId, onRestart }: RunActionsProps): React.JSX.Element {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'retry' | 'rerun' | 'export' | null>(null)

  async function handleRetry(): Promise<void> {
    setBusy('retry')
    setError(null)
    try {
      const resp = await retryRun(runId)
      onRestart?.(resp)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'retry failed')
    } finally {
      setBusy(null)
    }
  }

  async function handleRerun(): Promise<void> {
    setBusy('rerun')
    setError(null)
    try {
      const resp = await rerunRun(runId)
      onRestart?.(resp)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'rerun failed')
    } finally {
      setBusy(null)
    }
  }

  async function handleExport(): Promise<void> {
    setBusy('export')
    setError(null)
    try {
      const payload = await exportRun(runId)
      downloadExport(runId, payload)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'export failed')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="run-actions" data-testid="run-actions">
      <button
        type="button"
        className="btn btn-secondary"
        onClick={() => void handleRetry()}
        disabled={busy !== null}
        data-testid="run-action-retry"
      >
        {busy === 'retry' ? 'Retrying...' : 'Retry'}
      </button>
      <button
        type="button"
        className="btn btn-secondary"
        onClick={() => void handleRerun()}
        disabled={busy !== null}
        data-testid="run-action-rerun"
      >
        {busy === 'rerun' ? 'Starting...' : 'Re-run'}
      </button>
      <button
        type="button"
        className="btn btn-secondary"
        onClick={() => void handleExport()}
        disabled={busy !== null}
        data-testid="run-action-export"
      >
        {busy === 'export' ? 'Exporting...' : 'Export'}
      </button>
      {error && <span className="run-actions-error" role="alert">{error}</span>}
    </div>
  )
}

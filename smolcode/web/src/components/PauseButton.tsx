// PauseButton: pauses or resumes a run via POST /api/runs/{id}/pause|resume.
//
// Phase 2 (decision 0025 §6.4): the pause / resume controls. When the
// run is ``running``, the button shows "Pause"; when ``paused``, it
// shows "Resume". Disabled in all other states (pending, terminal).
//
// The button is intentionally minimal -- a single click that toggles
// state. The Inspector / QueuePane surfaces the resulting ``run.paused``
// + ``run.resumed`` events.
import { useState } from 'react'
import { pauseRun, resumeRun } from '../api'

export type RunStatus =
  | 'pending'
  | 'running'
  | 'awaiting_approval'
  | 'paused'
  | 'done'
  | 'error'
  | 'stopped'

interface Props {
  runId: string
  status: RunStatus | string
  /** Optional callback fired after a successful pause / resume. */
  onChanged?: () => void
}

export function PauseButton({ runId, status, onChanged }: Props) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const handle = async () => {
    setBusy(true)
    setErr(null)
    try {
      if (status === 'paused') {
        await resumeRun(runId)
      } else {
        await pauseRun(runId)
      }
      onChanged && onChanged()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const canPause = status === 'running' || status === 'awaiting_approval'
  const canResume = status === 'paused'
  const disabled = busy || (!canPause && !canResume)
  const label = status === 'paused' ? 'Resume' : 'Pause'
  return (
    <button className="btn btn-secondary pause-btn" onClick={handle} disabled={disabled} title="Resume will re-initialize the sandbox (~5s delay)">
      {busy ? (status === 'paused' ? 'Resuming...' : 'Pausing...') : label}
      {err && <span className="muted small"> ({err})</span>}
    </button>
  )
}

// StopButton: POSTs /api/runs/{id}/stop. Disables while in flight.
import { useState } from 'react'
import { postStop } from '../api'

interface Props {
  runId: string
  onStopped?: () => void
}

export function StopButton({ runId, onStopped }: Props) {
  const [stopping, setStopping] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const handle = async () => {
    setStopping(true)
    setErr(null)
    try {
      await postStop(runId)
      onStopped && onStopped()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setStopping(false)
    }
  }
  return (
    <button className="btn btn-danger" onClick={handle} disabled={stopping}>
      {stopping ? 'Stopping...' : 'Stop'}
      {err && <span className="muted small"> ({err})</span>}
    </button>
  )
}
// RunComposer: task input + run button (M9 + M11).
// Forwards provider / model / api-key overrides to /api/runs.
//
// M11 contract:
//   - provider: optional id from /api/providers
//   - model: optional model id; falls back to server's default if absent
//   - keyValue: optional stored key; only attached if apiKeyEnv is set and
//     keyValue is non-empty
//
// Phase 2 (decision 0025 §6.4 A5): the task textarea is now a
// FileMentionInput -- the user can type ``@`` to autocomplete file
// paths from the active project tree. Server-side ``_attach_mentions``
// does the actual file-content inlining once the run starts.

import { useState } from 'react'
import { startRun } from '../api'
import { FileMentionInput } from './FileMentionInput'

interface Props {
  tier: string
  provider: string | null
  model: string | null
  keyValue: string | null
  /** env var name the backend expects for this provider (e.g. "OPENAI_API_KEY"). */
  apiKeyEnv: string | null
  /** Phase 1 (decision 0025 §6.3): attach the run to a chat session + project. */
  sessionId?: string | null
  project?: string | null
  onSubmitted: (runId: string) => void
}

export function RunComposer({
  tier,
  provider,
  model,
  keyValue,
  apiKeyEnv,
  sessionId,
  project,
  onSubmitted,
}: Props) {
  const [task, setTask] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handle = async () => {
    setError(null)
    const t = task.trim()
    if (!t) {
      setError('Task cannot be empty')
      return
    }
    const keys: Record<string, string> | undefined =
      apiKeyEnv && keyValue && keyValue.length > 0 ? { [apiKeyEnv]: keyValue } : undefined
    setSubmitting(true)
    try {
      const r = await startRun(t, tier, {
        provider: provider ?? undefined,
        model: model ?? undefined,
        keys,
        session_id: sessionId ?? undefined,
        project: project ?? undefined,
      })
      setTask('')
      onSubmitted(r.run_id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const viaHint =
    provider && model
      ? `via ${provider} / ${model}`
      : provider
        ? `via ${provider} (server default model)`
        : 'via server defaults'

  return (
    <div className="run-composer">
      <FileMentionInput
        value={task}
        onChange={setTask}
        project={project ?? null}
        disabled={submitting}
      />
      <div className="run-composer-row">
        <button className="btn btn-primary" onClick={handle} disabled={submitting}>
          {submitting ? 'Starting...' : 'Run'}
        </button>
        <span className="small muted via-hint">{viaHint}</span>
      </div>
      {error && <div className="error-banner">{error}</div>}
    </div>
  )
}

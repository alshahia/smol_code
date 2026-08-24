// SessionsPane: left-pane chat-session manager (Phase 1, decision 0025 sec 6.3).
//
// Renders a list of chat sessions (newest first) with create / rename /
// delete controls. Clicking a session selects it (caller wires the
// selection into the run.started filter). The detail view shows the
// raw event stream of the active session.
//
// Scoped to the active project via the `project` prop; when null,
// lists / mutates sessions in the legacy workspace.
import { useCallback, useEffect, useState } from 'react'
import {
  createSession as apiCreateSession,
  deleteSession as apiDeleteSession,
  listSessions as apiListSessions,
  renameSession as apiRenameSession,
  type SessionInfo,
} from '../api'

interface Props {
  /** Active project name; null = legacy workspace. */
  project: string | null
  /** Currently selected session id (caller-owned state). */
  activeSessionId?: string | null
  onSelect?: (sessionId: string | null) => void
  /** Refresh trigger: bump to force a re-list. */
  refreshTrigger?: number
}

export function SessionsPane({ project, activeSessionId, onSelect, refreshTrigger }: Props) {
  const [sessions, setSessions] = useState<SessionInfo[]>([])
  const [creating, setCreating] = useState<boolean>(false)
  const [newName, setNewName] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState<string>('')

  const refresh = useCallback(async () => {
    try {
      const r = await apiListSessions(project)
      setSessions(r.sessions)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [project])

  useEffect(() => {
    void refresh()
  }, [refresh, refreshTrigger])

  const handleCreate = async () => {
    setError(null)
    setCreating(true)
    try {
      const r = await apiCreateSession({ name: newName.trim() || null }, project)
      setNewName('')
      onSelect?.(r.id)
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete session ' + id + '? This cannot be undone.')) return
    setError(null)
    try {
      await apiDeleteSession(id, project)
      if (activeSessionId === id) onSelect?.(null)
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const startRename = (s: SessionInfo) => {
    setRenamingId(s.id)
    setRenameValue(s.name || '')
  }

  const commitRename = async () => {
    if (!renamingId) return
    setError(null)
    try {
      await apiRenameSession(renamingId, renameValue, project)
      setRenamingId(null)
      setRenameValue('')
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const cancelRename = () => {
    setRenamingId(null)
    setRenameValue('')
  }

  return (
    <div className="sessions-pane">
      <div className="sessions-create">
        <input
          type="text"
          className="sessions-name-input"
          placeholder="New session name (optional)"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void handleCreate()
          }}
          disabled={creating}
        />
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => void handleCreate()}
          disabled={creating}
        >
          New
        </button>
      </div>
      {error && <div className="error small">{error}</div>}
      {sessions.length === 0 ? (
        <div className="muted small">No sessions yet.</div>
      ) : (
        <ul className="sessions-list">
          {sessions.map((s) => {
            const isActive = activeSessionId === s.id
            const isRenaming = renamingId === s.id
            return (
              <li
                key={s.id}
                className={'sessions-item' + (isActive ? ' active' : '')}
              >
                {isRenaming ? (
                  <div className="sessions-rename">
                    <input
                      autoFocus
                      type="text"
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') void commitRename()
                        if (e.key === 'Escape') cancelRename()
                      }}
                    />
                    <button
                      type="button"
                      className="btn btn-secondary small"
                      onClick={() => void commitRename()}
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary small"
                      onClick={cancelRename}
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <>
                    <button
                      type="button"
                      className="sessions-row"
                      onClick={() => onSelect?.(s.id)}
                      title={s.id}
                    >
                      <span className="sessions-name">
                        {s.name || '(unnamed ' + s.id.slice(0, 8) + ')'}
                      </span>
                      <span className="sessions-meta small muted">
                        {s.run_count} run{s.run_count === 1 ? '' : 's'}
                      </span>
                    </button>
                    <div className="sessions-actions">
                      <button
                        type="button"
                        className="btn btn-secondary small"
                        onClick={() => startRename(s)}
                        title="Rename"
                      >
                        Rename
                      </button>
                      <button
                        type="button"
                        className="btn btn-secondary small danger"
                        onClick={() => void handleDelete(s.id)}
                        title="Delete"
                      >
                        Delete
                      </button>
                    </div>
                  </>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

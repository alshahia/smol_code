// ProjectSwitcher: header dropdown for the active project (Phase 1, decision 0025 sec 6.3).
//
// Lists Settings.projects; selecting one propagates to the caller via
// onChange. When no projects are configured, renders a single
// "(workspace)" option so the dropdown stays visible (the SPA is
// otherwise confusingly empty).
//
// Inline "New project" form creates a project at runtime; on success
// the new project is selected automatically.
import { useEffect, useState } from 'react'
import {
  createProject as apiCreateProject,
  deleteProject as apiDeleteProject,
  listProjects as apiListProjects,
  type ProjectInfo,
} from '../api'

interface Props {
  /** Currently active project name; null = legacy workspace. */
  value: string | null
  /** Called with the new active project name. */
  onChange: (project: string | null) => void
  /** Refresh trigger: bump to force a re-list. */
  refreshTrigger?: number
}

export function ProjectSwitcher({ value, onChange, refreshTrigger }: Props) {
  const [projects, setProjects] = useState<ProjectInfo[]>([])
  const [creating, setCreating] = useState<boolean>(false)
  const [newName, setNewName] = useState<string>('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const r = await apiListProjects()
        if (!cancelled) setProjects(r.projects)
      } catch (e) {
        if (!cancelled) setError((e as Error).message)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [refreshTrigger])

  const handleCreate = async () => {
    const n = newName.trim()
    if (!n) return
    setError(null)
    setCreating(true)
    try {
      const p = await apiCreateProject({ name: n })
      setNewName('')
      setProjects((prev) => [...prev, p])
      onChange(p.name)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (name: string) => {
    if (!confirm('Remove project ' + name + ' from this session? (on-disk files are NOT deleted.)')) {
      return
    }
    setError(null)
    try {
      await apiDeleteProject(name)
      setProjects((prev) => prev.filter((p) => p.name !== name))
      if (value === name) onChange(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="project-switcher">
      <select
        className="project-select"
        aria-label="Active project"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
      >
        <option value="">(workspace)</option>
        {projects.map((p) => (
          <option key={p.name} value={p.name}>
            {p.name}
          </option>
        ))}
      </select>
      {value && (
        <button
          type="button"
          className="btn btn-secondary small"
          onClick={() => void handleDelete(value)}
          title="Remove project from this session"
        >
          -P
        </button>
      )}
      {creating ? (
        <span className="muted small">creating...</span>
      ) : (
        <span className="project-add">
          <input
            type="text"
            placeholder="+ project"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void handleCreate()
            }}
            className="project-add-input"
          />
        </span>
      )}
      {error && <div className="error small">{error}</div>}
    </div>
  )
}

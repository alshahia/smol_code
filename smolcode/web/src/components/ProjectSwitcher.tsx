// ProjectSwitcher: header dropdown for the active project (Phase 1, decision 0025 sec 6.3).
//
// Phase 4 F4 (decision 0037) - outside-workspace selector:
//   - Path input + Browse button next to the existing Name input.
//     webkitdirectory cannot yield an absolute path (browser security),
//     so the Browse button prefills the Path field with the picked
//     folder's top-level name and surfaces an inline hint that the
//     user must paste the absolute path manually.
//   - Recent projects dropdown persisted in
//     localStorage.smolcode.recentProjects.v1 (capped at 8, dedup, FIFO).
//   - Outside-workspace notice renders when the typed path resolves
//     outside the live workspace (case-insensitive containment after
//     normalising path separators). Just informational; the BE does
//     the final 400 on a non-existent path.
//
// Backwards-compatible: when the Path input is left empty, handleCreate
// sends {name} as before and the BE defaults the root to <workspace>/<name>.
import { useEffect, useRef, useState } from 'react'
import {
  createProject as apiCreateProject,
  deleteProject as apiDeleteProject,
  listProjects as apiListProjects,
  type ProjectInfo,
} from '../api'

/** A project the user has recently created in this browser. */
export interface RecentProject {
  name: string
  root: string
  last_used: number
}

/** Max number of entries kept in the recent-projects list. */
export const MAX_RECENT_PROJECTS = 8
/** localStorage key for the recent-projects dropdown (Phase 4). */
export const RECENT_PROJECTS_KEY = 'smolcode.recentProjects.v1'

interface Props {
  /** Currently active project name; null = legacy workspace. */
  value: string | null
  /** Called with the new active project name. */
  onChange: (project: string | null) => void
  /** Refresh trigger: bump to force a re-list. */
  refreshTrigger?: number
  workspace?: string | null
}

function loadRecents(): RecentProject[] {
  if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(RECENT_PROJECTS_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    const out: RecentProject[] = []
    for (const item of parsed) {
      if (item && typeof item === 'object' && typeof (item as RecentProject).name === 'string' && typeof (item as RecentProject).root === 'string' && typeof (item as RecentProject).last_used === 'number') out.push(item as RecentProject)
    }
    return out.slice(0, MAX_RECENT_PROJECTS)
  } catch { return [] }
}

function saveRecents(recents: RecentProject[]): void {
  if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') return
  try { window.localStorage.setItem(RECENT_PROJECTS_KEY, JSON.stringify(recents.slice(0, MAX_RECENT_PROJECTS))) } catch {}
}

export function isOutsideWorkspace(target: string, workspace: string | null | undefined): boolean {
  const t = target.trim(); if (!t) return false
  const ws = (workspace ?? '').trim(); if (!ws) return false
  const norm = (p: string) => p.replace(/[\\/]+/g, '/').replace(/\/$/, '').toLowerCase()
  const a = norm(t); const b = norm(ws)
  if (a === b) return false
  const lastA = a.split('/').pop() ?? ''
  if (a === b + '/' + lastA) return false
  return !a.startsWith(b + '/')
}

export function ProjectSwitcher({ value, onChange, refreshTrigger, workspace }: Props) {
  const [projects, setProjects] = useState<ProjectInfo[]>([])
  const [creating, setCreating] = useState<boolean>(false)
  const [newName, setNewName] = useState<string>('')
  const [newPath, setNewPath] = useState<string>('')
  const [recents, setRecents] = useState<RecentProject[]>([])
  const [error, setError] = useState<string | null>(null)
  const [browseKey, setBrowseKey] = useState<number>(0)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => { setRecents(loadRecents()) }, [])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try { const r = await apiListProjects(); if (!cancelled) setProjects(r.projects) } catch (e) { if (!cancelled) setError((e as Error).message) }
    })()
    return () => { cancelled = true }
  }, [refreshTrigger])

  const pushRecent = (rp: RecentProject) => {
    setRecents((prev) => {
      const without = prev.filter((r) => r.name.toLowerCase() !== rp.name.toLowerCase())
      const next = [{ ...rp, last_used: Date.now() }, ...without].slice(0, MAX_RECENT_PROJECTS)
      saveRecents(next); return next
    })
  }

  const handleCreate = async () => {
    const n = newName.trim(); if (!n) return
    setError(null); setCreating(true)
    try {
      const root = newPath.trim()
      const p = await apiCreateProject(root ? { name: n, root } : { name: n })
      setNewName(''); setNewPath('')
      setProjects((prev) => [...prev, p])
      pushRecent({ name: p.name, root: p.root, last_used: Date.now() })
      onChange(p.name)
    } catch (e) { setError((e as Error).message) } finally { setCreating(false) }
  }

  const handleDelete = async (name: string) => {
    if (!confirm('Remove project ' + name + ' from this session? (on-disk files are NOT deleted.)')) return
    setError(null)
    try {
      await apiDeleteProject(name)
      setProjects((prev) => prev.filter((p) => p.name !== name))
      setRecents((prev) => { const next = prev.filter((r) => r.name !== name); saveRecents(next); return next })
      if (value === name) onChange(null)
    } catch (e) { setError((e as Error).message) }
  }

  const handleBrowse = () => { fileInputRef.current?.click() }

  const handlePickFolder = (e: React.ChangeEvent<HTMLInputElement>) => {
    const list = e.target.files; if (!list || list.length === 0) return
    const first = list[0]
    const rel = first.webkitRelativePath || first.name
    const parts = rel.split('/').filter(Boolean); if (parts.length === 0) return
    const top = parts[0]
    setNewPath((cur) => (cur.trim() ? cur : '<paste absolute path containing ' + top + '>'))
    setBrowseKey((k) => k + 1)
  }

  const handlePickRecent = (rp: RecentProject) => { setNewName(rp.name); setNewPath(rp.root) }
  const handleClearRecents = () => { setRecents([]); saveRecents([]) }

  const outsideNotice =
    workspace && newPath.trim() && isOutsideWorkspace(newPath, workspace)
      ? "this project's files will live outside the default workspace (" + workspace + '); full_access can still reach anywhere.'
      : null

  return (
    <div className='project-switcher'>
      <select className='project-select' aria-label='Active project' value={value ?? ''} onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}>
        <option value=''>(workspace)</option>
        {projects.map((p) => (<option key={p.name} value={p.name}>{p.name}</option>))}
      </select>
      {value && (
        <button type='button' className='btn btn-secondary small' onClick={() => void handleDelete(value)} title='Remove project from this session'>-P</button>
      )}
      {creating ? (
        <span className='muted small'>creating...</span>
      ) : (
        <span className='project-add'>
          <input type='text' placeholder='+ project' value={newName} onChange={(e) => setNewName(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void handleCreate() }} className='project-add-input' aria-label='New project name' />
          <input type='text' placeholder='path (default: workspace/<name>)' value={newPath} onChange={(e) => setNewPath(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void handleCreate() }} className='project-add-path-input' aria-label='New project root path' />
          <button type='button' className='btn btn-secondary small' onClick={handleBrowse} title='Pick a folder (prefills the path field with its name; browsers cannot expose absolute paths)' aria-label='Browse for project folder'>Browse</button>
          <input key={browseKey} ref={fileInputRef} type='file' data-testid='project-browse-input' {...({ webkitdirectory: '', directory: '', multiple: true } as any)} style={{ display: 'none' }} onChange={handlePickFolder} />
          {recents.length > 0 && (
            <select className='project-recent-select' aria-label='Recent projects' value='' onChange={(e) => { const idx = Number(e.target.value); if (Number.isFinite(idx) && idx >= 0) { const rp = recents[idx]; if (rp) handlePickRecent(rp) } }}>
              <option value=''>recent...</option>
              {recents.map((r, i) => (<option key={r.name} value={i}>{r.name} ({r.root})</option>))}
            </select>
          )}
          {recents.length > 0 && (
            <button type='button' className='btn btn-secondary small' onClick={handleClearRecents} title='Clear recent projects list' aria-label='Clear recent projects'>xR</button>
          )}
        </span>
      )}
      {outsideNotice && (<div className='project-outside-notice small' role='note'>{outsideNotice}</div>)}
      {error && <div className='error small'>{error}</div>}
    </div>
  )
}

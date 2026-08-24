// WorkspaceTree: shows the workspace tree from /api/workspace/tree (M10).
// Highlights files that the active run has touched (write_file/patch_file).
// Refreshes every 10 seconds while the component is mounted.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { getWorkspaceTree, type TreeEntry, type WorkspaceTreeResponse } from '../api'

interface Props {
  workspaceRoot: string
  touchedPaths?: ReadonlyArray<string>
  maxEntries?: number
  maxDepth?: number
  // Phase 0 (decision 0025, B11): bumped by the parent on each
  // diff.proposed / diff.resolved event to force an immediate tree
  // refresh (instead of waiting for the 10s poll). undefined / 0
  // means "no external trigger; rely on the internal interval".
  refreshTrigger?: number
  // Phase 1 (decision 0025 §6.3): scope the tree to the active project.
  // null/undefined = legacy workspace; string = project name.
  project?: string | null
}

interface TreeNode {
  name: string
  relPath: string
  isDir: boolean
  size: number
  children: TreeNode[]
}

function buildTree(entries: TreeEntry[]): TreeNode[] {
  // Group entries by their parent directory.
  const byParent: Record<string, TreeEntry[]> = { '': [] }
  for (const e of entries) {
    const parent = e.rel_path.includes('/') ? e.rel_path.replace(/\/[^/]*$/, '') : ''
    if (!byParent[parent]) byParent[parent] = []
    byParent[parent].push(e)
  }
  function make(e: TreeEntry): TreeNode {
    return {
      name: e.name,
      relPath: e.rel_path,
      isDir: e.is_dir,
      size: e.size,
      children: [],
    }
  }
  function build(rel: string): TreeNode[] {
    const list = byParent[rel] || []
    return list.map((e) => {
      const node = make(e)
      if (e.is_dir) node.children = build(e.rel_path)
      return node
    })
  }
  return build('')
}

function NodeRow({
  node,
  depth,
  touchedSet,
}: {
  node: TreeNode
  depth: number
  touchedSet: Set<string>
}) {
  const [open, setOpen] = useState(depth < 2)
  const isTouched = touchedSet.has(node.relPath)
  const pad = { paddingLeft: 8 + depth * 16 }
  if (!node.isDir) {
    return (
      <div className={'tree-row tree-file' + (isTouched ? ' tree-touched' : '')} style={pad}>
        <span className="tree-icon">·</span>
        <span className="tree-name">{node.name}</span>
        <span className="tree-size muted">{node.size}</span>
      </div>
    )
  }
  return (
    <div className={'tree-row tree-dir' + (isTouched ? ' tree-touched' : '')} style={pad}>
      <span
        className="tree-toggle"
        onClick={() => setOpen(!open)}
        role="button"
        aria-label={open ? 'Collapse' : 'Expand'}
      >
        {open ? '▾' : '▸'}
      </span>
      <span className="tree-name">{node.name}/</span>
      {open && node.children.map((c) => <NodeRow key={c.relPath} node={c} depth={depth + 1} touchedSet={touchedSet} />)}
    </div>
  )
}

export function WorkspaceTree({ workspaceRoot, touchedPaths, maxEntries, maxDepth, refreshTrigger, project }: Props) {
  const [data, setData] = useState<WorkspaceTreeResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  const refresh = useCallback(async () => {
    setRefreshing(true)
    try {
      const r = await getWorkspaceTree(maxEntries, maxDepth, project)
      setData(r)
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRefreshing(false)
    }
  }, [maxEntries, maxDepth, project])

  useEffect(() => {
    // Schedule the initial refresh via setTimeout so the setState inside
    // refresh() doesn't fire synchronously during the effect (xlint).
    const schedule = () => { window.setTimeout(() => { void refresh() }, 0) }
    schedule()
    const id = window.setInterval(schedule, 10000)
    return () => window.clearInterval(id)
  }, [refresh])

  // Phase 0 (decision 0025, B11): refresh immediately when the parent
  // bumps ``refreshTrigger`` -- typically on every diff.proposed /
  // diff.resolved event so the user sees the touched file appear in
  // the tree within ~100ms instead of waiting for the 10s poll. The
  // setTimeout(0) defers the state update so xlint's set-state-in-effect
  // warning does not fire (matches the existing interval scheduler).
  useEffect(() => {
    if (refreshTrigger === undefined || refreshTrigger === 0) return
    const id = window.setTimeout(() => { void refresh() }, 0)
    return () => window.clearTimeout(id)
  }, [refreshTrigger, refresh])

  const tree = useMemo(() => (data ? buildTree(data.entries) : []), [data])
  const touchedSet = useMemo(() => new Set(touchedPaths || []), [touchedPaths])

  return (
    <div className="workspace-tree" title={workspaceRoot}>
      <div className="workspace-tree-head">
        <span className="workspace-tree-root" title={workspaceRoot}>
          {workspaceRoot.split(/[\\/]/).slice(-2).join('/')}
        </span>
        <button className="btn btn-secondary btn-sm" onClick={() => void refresh()} disabled={refreshing}>
          {refreshing ? '...' : 'Refresh'}
        </button>
      </div>
      {error && <div className="error-banner">{error}</div>}
      {data && data.entries.length === 0 && <div className="muted small">Workspace is empty</div>}
      {data && data.truncated && (
        <div className="muted small">
          Showing first {data.entries.length} of (more) entries (truncated). Raise ?max_entries to see more.
        </div>
      )}
      {tree.map((node) => (
        <NodeRow key={node.relPath} node={node} depth={0} touchedSet={touchedSet} />
      ))}
    </div>
  )
}

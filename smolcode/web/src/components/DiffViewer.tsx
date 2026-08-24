// DiffViewer: renders a unified-diff text with color-coded hunks (M10).
// When ``hunks`` is provided (structured payload from the backend), the
// viewer renders them directly; otherwise it falls back to parsing the
// raw ``raw_diff`` text. Either input produces the same visual output.
//
// The component is read-only by default. Pass ``onEdit`` to enable an
// inline editor that lets the user rewrite the proposed content before
// approving (sent as ``edited_after`` to the backend).

import { useMemo, useState } from 'react'
import type { DiffHunk, DiffStats } from '../api'

interface Props {
  before: string
  after: string
  rawDiff?: string
  hunks?: DiffHunk[]
  stats?: DiffStats
  editable?: boolean
  onEdit?: (newAfter: string) => void
}

type ViewLine = { tag: ' ' | '-' | '+'; text: string; oldLine?: number; newLine?: number }

function buildViewLines(hunks: DiffHunk[]): ViewLine[] {
  const out: ViewLine[] = []
  let oldNo = 0
  let newNo = 0
  for (const h of hunks) {
    if (h.op === 'equal') {
      for (const ln of h.before) {
        oldNo += 1
        newNo += 1
        out.push({ tag: ' ', text: ln, oldLine: oldNo, newLine: newNo })
      }
    } else if (h.op === 'replace') {
      for (const ln of h.before) {
        oldNo += 1
        out.push({ tag: '-', text: ln, oldLine: oldNo })
      }
      for (const ln of h.after) {
        newNo += 1
        out.push({ tag: '+', text: ln, newLine: newNo })
      }
    } else if (h.op === 'delete') {
      for (const ln of h.before) {
        oldNo += 1
        out.push({ tag: '-', text: ln, oldLine: oldNo })
      }
    } else if (h.op === 'insert') {
      for (const ln of h.after) {
        newNo += 1
        out.push({ tag: '+', text: ln, newLine: newNo })
      }
    }
  }
  return out
}

function parseRawDiff(rawDiff: string): ViewLine[] {
  // Minimal fallback parser: walks unified-diff text and emits view lines.
  // The backend normally provides ``hunks``; this is just a safety net.
  const out: ViewLine[] = []
  const lines = rawDiff.split(/\r?\n/)
  let oldNo = 0
  let newNo = 0
  let inHunk = false
  for (const ln of lines) {
    if (ln.startsWith('@@')) {
      inHunk = true
      oldNo = 0
      newNo = 0
      const m = ln.match(/@@ -(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@/)
      if (m) {
        oldNo = Number(m[1]) - 1
        newNo = Number(m[2]) - 1
      }
      continue
    }
    if (!inHunk) continue
    if (ln.startsWith('\\')) continue
    if (ln === '') {
      // Blank line: treat as a context line with empty content.
      oldNo += 1
      newNo += 1
      out.push({ tag: ' ', text: '', oldLine: oldNo, newLine: newNo })
      continue
    }
    const tag = ln[0]
    const content = ln.slice(1)
    if (tag === ' ') {
      oldNo += 1
      newNo += 1
      out.push({ tag: ' ', text: content, oldLine: oldNo, newLine: newNo })
    } else if (tag === '-') {
      oldNo += 1
      out.push({ tag: '-', text: content, oldLine: oldNo })
    } else if (tag === '+') {
      newNo += 1
      out.push({ tag: '+', text: content, newLine: newNo })
    }
  }
  return out
}

export function DiffViewer({ before, after, rawDiff, hunks, stats, editable, onEdit }: Props) {
  const viewLines = useMemo<ViewLine[]>(() => {
    if (hunks && hunks.length > 0) return buildViewLines(hunks)
    if (rawDiff) return parseRawDiff(rawDiff)
    return []
  }, [hunks, rawDiff])

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(after)

  const noChanges = stats && !stats.changed && stats.added === 0 && stats.removed === 0

  if (noChanges) {
    return <div className="diff-empty">No content changes</div>
  }
  if (viewLines.length === 0) {
    return <div className="diff-empty">Empty diff</div>
  }

  return (
    <div className="diff-viewer">
      {stats && (
        <div className="diff-stats">
          <span className="diff-stat-add">+{stats.added}</span>
          <span className="diff-stat-del">-{stats.removed}</span>
          <span className="muted small">{stats.same} unchanged</span>
        </div>
      )}
      {editable ? (
        <div className="diff-edit-toolbar">
          {!editing ? (
            <button className="btn btn-secondary" onClick={() => { setDraft(after); setEditing(true) }}>
              Edit proposed content
            </button>
          ) : (
            <>
              <button className="btn btn-primary" onClick={() => { onEdit?.(draft); setEditing(false) }}>
                Apply edit
              </button>
              <button className="btn btn-secondary" onClick={() => { setDraft(after); setEditing(false) }}>
                Cancel
              </button>
            </>
          )}
        </div>
      ) : null}
      {editing ? (
        <textarea
          className="diff-edit-area"
          value={draft}
          spellCheck={false}
          onChange={(e) => setDraft(e.target.value)}
          aria-label="Edit proposed file content"
        />
      ) : (
        <pre className="diff-body" role="region" aria-label="Diff content">
          {viewLines.map((ln, i) => (
            <div key={i} className={`diff-line diff-${ln.tag === ' ' ? 'ctx' : ln.tag === '-' ? 'del' : 'add'}`}>
              <span className="diff-gutter">{ln.oldLine ?? ''}</span>
              <span className="diff-gutter">{ln.newLine ?? ''}</span>
              <span className="diff-tag">{ln.tag === ' ' ? '' : ln.tag}</span>
              <span className="diff-text">{ln.text === '' ? '\u00A0' : ln.text}</span>
            </div>
          ))}
        </pre>
      )}
      {editable && !editing && before ? (
        <details className="diff-before">
          <summary>Show original</summary>
          <pre>{before}</pre>
        </details>
      ) : null}
    </div>
  )
}

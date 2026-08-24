// ApprovalModal: shown when an approval.requested or diff.proposed SSE
// event arrives (M9 + M10). Renders a modal overlay with the tool,
// summary, args, and three buttons: Approve, Deny, Approve for rest of
// run (auto).
//
// M10: when ``kind === 'diff'`` the modal renders a DiffViewer with
// the proposed before/after content, plus an inline editor that lets
// the user rewrite the proposed content (sent as ``edited_after``).

import { useState } from 'react'
import { DiffViewer } from './DiffViewer'
import type { DiffHunk, DiffStats } from '../api'

export interface PendingApproval {
  decisionId: string
  tool: string
  args: unknown
  summary: string
  // M10: kind drives the layout. 'destructive' = M9 destructive tool;
  // 'diff' = write_file/patch_file gate. Optional for backward compat.
  kind?: 'destructive' | 'diff' | string
  // M10: diff-specific fields.
  path?: string
  relPath?: string
  before?: string
  after?: string
  rawDiff?: string
  hunks?: DiffHunk[]
  stats?: DiffStats
}

interface Props {
  pending: PendingApproval | null
  onDecide: (approved: boolean, reason: string, editedAfter: string | null) => void
}

export function ApprovalModal({ pending, onDecide }: Props) {
  const [editedAfter, setEditedAfter] = useState<string | null>(null)
  if (!pending) return null
  const isDiff = pending.kind === 'diff'
  const argsJson = (() => {
    try {
      return JSON.stringify(pending.args, null, 2)
    } catch {
      return String(pending.args)
    }
  })()
  const effectiveAfter = editedAfter !== null ? editedAfter : (pending.after ?? '')
  return (
    <div className="approval-modal" role="dialog" aria-modal="true">
      <div className={'approval-card ' + (isDiff ? 'approval-card-wide' : '')}>
        <h3>{isDiff ? 'Awaiting approval: file change' : 'Awaiting approval'}</h3>
        <div className="approval-field">
          <span className="approval-label">Tool:</span> <code>{pending.tool}</code>
        </div>
        <div className="approval-field">
          <span className="approval-label">Summary:</span> {pending.summary}
        </div>
        {isDiff && pending.relPath ? (
          <div className="approval-field">
            <span className="approval-label">Path:</span> <code>{pending.relPath}</code>
          </div>
        ) : null}
        {!isDiff && (
          <div className="approval-field">
            <span className="approval-label">Args:</span>
            <pre className="approval-args">{argsJson}</pre>
          </div>
        )}
        {isDiff && pending.before !== undefined && pending.after !== undefined ? (
          <div className="approval-field">
            <DiffViewer
              before={pending.before}
              after={effectiveAfter}
              rawDiff={pending.rawDiff}
              hunks={pending.hunks}
              stats={pending.stats}
              editable={true}
              onEdit={(v) => setEditedAfter(v)}
            />
          </div>
        ) : null}
        <div className="approval-actions">
          <button className="btn btn-primary" onClick={() => { onDecide(true, 'user-approved', editedAfter); setEditedAfter(null) }}>
            {editedAfter !== null ? 'Apply + Approve' : 'Approve'}
          </button>
          <button className="btn btn-danger" onClick={() => { onDecide(false, 'user-denied', null); setEditedAfter(null) }}>
            Deny
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => { onDecide(true, 'auto-approve', editedAfter); setEditedAfter(null) }}
          >
            Approve (no more prompts this run)
          </button>
        </div>
      </div>
    </div>
  )
}

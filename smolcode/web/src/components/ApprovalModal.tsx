// ApprovalModal: shown when an approval.requested or diff.proposed SSE
// event arrives (M9 + M10). Renders a modal overlay with the tool,
// summary, args, and three buttons: Approve, Deny, Approve for rest of
// run (auto).
//
// M10: when the kind field equals 'diff' the modal renders a
// DiffViewer with the proposed before/after content plus an inline
// editor that lets the user rewrite the proposed content (sent as
// edited_after).
//
// v1.9.x (FE-6, B10): the modal additionally accepts an optional
// onAutoApproveToggle callback. It is called with true when the
// user clicks the 'no more prompts this run' button so the parent
// can render a mid-run 'Auto-approve is ON' banner with a Disable
// button. Disabling the underlying server-side flag requires a
// followup endpoint; the client-side toggle only manages the
// visible banner.

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
  // Phase 3 F3 (decision 0036): 'outside_root' = the Q2 outside-project
  // write gate; renders the FULL absolute target path + three buttons
  // (Deny / Approve once / Approve for this session for THIS path).
  kind?: 'destructive' | 'diff' | 'outside_root' | string
  // M10: diff-specific fields.
  path?: string
  relPath?: string
  before?: string
  after?: string
  rawDiff?: string
  hunks?: DiffHunk[]
  stats?: DiffStats
  // Phase 3 F3: outside_root-specific fields. absoluteTarget is the
  // FULL path the write would land at (monospace, prominent in the
  // modal). effectiveCwd is the project root the user opted into for
  // context. allowedActions is the policy contract -- the BE guarantees
  // ["deny","approve_once","approve_session_for_path"] but the SPA
  // reads it from the event so the modal stays in sync if the BE adds
  // new outcomes later.
  absoluteTarget?: string
  effectiveCwd?: string
  allowedActions?: string[]
}

interface Props {
  pending: PendingApproval | null
  onDecide: (approved: boolean, reason: string, editedAfter: string | null) => void
  /**
   * v1.9.x (FE-6): invoked with true when the user clicks the
   * 'no more prompts this run' button. The parent uses this to
   * render the mid-run auto-approve banner.
   */
  onAutoApproveToggle?: (active: boolean) => void
}

export function ApprovalModal({ pending, onDecide, onAutoApproveToggle }: Props) {
  const [editedAfter, setEditedAfter] = useState<string | null>(null)
  if (!pending) return null
  const isDiff = pending.kind === 'diff'
  // Phase 3 F3 (decision 0036): outside_root variant renders a
  // distinct layout (Q2 BLOCK + full-path modal + per-session per-path
  // allowlist). The render branch below replaces both the destructive
  // args dump AND the diff viewer for this kind.
  const isOutsideRoot = pending.kind === 'outside_root'
  const argsJson = (() => {
    try {
      return JSON.stringify(pending.args, null, 2)
    } catch {
      return String(pending.args)
    }
  })()
  const effectiveAfter = editedAfter !== null ? editedAfter : (pending.after ?? '')
  function approve(auto: boolean): void {
    onDecide(true, auto ? 'auto-approve' : 'user-approved', editedAfter)
    if (auto) onAutoApproveToggle?.(true)
    setEditedAfter(null)
  }
  function deny(): void {
    onDecide(false, 'user-denied', null)
    setEditedAfter(null)
  }
  // Phase 3 F3: outside_root three-button flow. Reasons map 1:1 to
  // the BE's allowed_actions; the BE's _resolve_outside_root_decision
  // translates them into the action discriminator + the optional
  // SessionState.outside_root_allowlist mutation.
  function outsideDeny(): void {
    onDecide(false, 'user-denied-outside-root', null)
  }
  function outsideApproveOnce(): void {
    onDecide(true, 'user-once-outside-root', null)
  }
  function outsideApproveSessionForPath(): void {
    onDecide(true, 'user-session-for-path-outside-root', null)
  }
  return (
    <div className="approval-modal" role="dialog" aria-modal="true">
      <div
        className={
          'approval-card ' +
          (isDiff || isOutsideRoot ? 'approval-card-wide' : '')
        }
      >
        <h3>
          {isOutsideRoot
            ? 'Outside-project write'
            : isDiff
              ? 'Awaiting approval: file change'
              : 'Awaiting approval'}
        </h3>
        {!isOutsideRoot && (
          <>
            <div className="approval-field">
              <span className="approval-label">Tool:</span> <code>{pending.tool}</code>
            </div>
            <div className="approval-field">
              <span className="approval-label">Summary:</span> {pending.summary}
            </div>
          </>
        )}
        {isDiff && pending.relPath ? (
          <div className="approval-field">
            <span className="approval-label">Path:</span> <code>{pending.relPath}</code>
          </div>
        ) : null}
        {isOutsideRoot && pending.absoluteTarget ? (
          <>
            <div className="approval-field">
              <span className="approval-label">Tool:</span> <code>{pending.tool}</code>
            </div>
            <div className="approval-field outside-root-target">
              <span className="approval-label">Writing to:</span>
              <code className="outside-root-path">{pending.absoluteTarget}</code>
            </div>
            {pending.effectiveCwd ? (
              <div className="approval-field">
                <span className="approval-label">Project root:</span> <code>{pending.effectiveCwd}</code>
              </div>
            ) : null}
            <div className="approval-field muted small">
              This path is outside the project root you opted into.
              Pick how to handle this write.
            </div>
          </>
        ) : null}
        {!isDiff && !isOutsideRoot && (
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
          {isOutsideRoot ? (
            <>
              <button className="btn btn-danger" onClick={outsideDeny}>
                Deny
              </button>
              <button className="btn btn-primary" onClick={outsideApproveOnce}>
                Approve once
              </button>
              <button
                className="btn btn-secondary"
                onClick={outsideApproveSessionForPath}
                title="Add this absolute target to the per-session per-path allowlist. Subsequent writes to the same path auto-approve without re-prompting."
              >
                Approve for this session for THIS path
              </button>
            </>
          ) : (
            <>
              <button className="btn btn-primary" onClick={() => approve(false)}>
                {editedAfter !== null ? 'Apply + Approve' : 'Approve'}
              </button>
              <button className="btn btn-danger" onClick={deny}>
                Deny
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => approve(true)}
              >
                Approve (no more prompts this run)
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
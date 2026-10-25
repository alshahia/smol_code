// Inline release gate. It belongs to the stage, not to a floating modal:
// the run, its evidence and the decision stay in one place. Approval is
// bound to exactly one held decision, and every path maps to an explicit
// server reason so the audit chain records what the human chose.

import type { PendingApproval } from '../ApprovalModal'
import { Icon } from './Icon'

interface Props {
  pending: PendingApproval
  editedAfter: string | null
  onDecide: (approved: boolean, reason: string, editedAfter: string | null) => void
  onAutoApprove: () => void
  onOpenChanges: () => void
}

export function ApprovalGate({ pending, editedAfter, onDecide, onAutoApprove, onOpenChanges }: Props) {
  const isDiff = pending.kind === 'diff'
  const isOutside = pending.kind === 'outside_root'

  if (isOutside) {
    return (
      <div className="gate-dock" role="region" aria-label="Approval gate">
        <div className="gate-mark"><Icon name="shield" size={17} /></div>
        <div className="gate-copy">
          <strong>Outside-root write held</strong>
          <span>{pending.absoluteTarget || pending.summary}</span>
        </div>
        <div className="gate-actions">
          <button type="button" className="btn btn-danger" onClick={() => onDecide(false, 'user-denied-outside-root', null)}>
            Deny
          </button>
          <button type="button" className="btn btn-primary" onClick={() => onDecide(true, 'user-once-outside-root', null)}>
            Approve once
          </button>
          <button
            type="button"
            className="btn"
            title="Allow writes to this exact path for the rest of this session."
            onClick={() => onDecide(true, 'user-session-for-path-outside-root', null)}
          >
            Approve session for this path
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="gate-dock" role="region" aria-label="Approval gate">
      <div className="gate-mark"><Icon name={isDiff ? 'file' : 'shield'} size={17} /></div>
      <div className="gate-copy">
        <strong>{isDiff ? 'Change held for release' : 'Destructive action held'}</strong>
        <span>
          {isDiff
            ? [pending.relPath || pending.path, pending.stats ? '+' + pending.stats.added + ' −' + pending.stats.removed : ''].filter(Boolean).join(' · ')
            : pending.summary}
        </span>
      </div>
      <div className="gate-actions">
        <button type="button" className="btn btn-primary" onClick={() => onDecide(true, 'user-approved', editedAfter)}>
          {editedAfter !== null ? 'Apply + approve' : 'Approve'}
        </button>
        <button type="button" className="btn btn-danger" onClick={() => onDecide(false, 'user-denied', null)}>
          Deny
        </button>
        <button type="button" className="btn" onClick={onAutoApprove}>
          No more prompts this run
        </button>
        <button type="button" className="btn btn-ghost" onClick={onOpenChanges}>
          Details
        </button>
      </div>
      <div className="gate-detail">
        <Icon name="shield" size={11} /> One decision releases one {isDiff ? 'write' : 'action'};
        {pending.tool ? <> the tool <code>{pending.tool}</code>,</> : null} reason and decision are appended to the audit chain.
      </div>
    </div>
  )
}

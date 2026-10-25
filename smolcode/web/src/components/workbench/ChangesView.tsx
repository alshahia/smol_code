// Changes: the review surface for a held diff or a held tool action.
// The decision itself lives in the inline gate at the bottom of the stage,
// so the run never loses its place and the composer is never displaced.

import type { PendingApproval } from '../ApprovalModal'
import { DiffViewer } from '../DiffViewer'
import { Icon } from './Icon'

interface ChangesViewProps {
  pending: PendingApproval | null
  lastDiff: PendingApproval | null
  editedAfter: string | null
  onEdit: (next: string) => void
  onOpenFile: (path: string) => void
  onCopy: (text: string, label: string) => void
}

export function ChangesView({ pending, lastDiff, editedAfter, onEdit, onOpenFile, onCopy }: ChangesViewProps) {
  const diff = pending?.kind === 'diff' ? pending : lastDiff
  const held = pending

  return (
    <div className="changes">
      <div className="changes-head">
        <div>
          <h2>{held ? (held.kind === 'diff' ? 'A change is held for release.' : 'An action is held for approval.') : 'No change is on the table.'}</h2>
          <p>
            {held
              ? held.kind === 'diff'
                ? 'Read the proposed content, edit it if needed, then release or deny it at the gate.'
                : 'The run needs a human decision before it can touch this resource.'
              : lastDiff
                ? 'The last proposed change, kept here for reference.'
                : 'When the run proposes an edit, it will appear in this tab and at the gate.'}
          </p>
        </div>
        <div className="changes-actions">
          {diff?.rawDiff ? (
            <button
              type="button"
              className="btn"
              onClick={() => onCopy(diff.rawDiff || '', 'patch copied')}
            >
              <Icon name="copy" size={13} /> Copy patch
            </button>
          ) : null}
          {diff && (diff.relPath || diff.path) ? (
            <button
              type="button"
              className="btn"
              onClick={() => onOpenFile(diff.relPath || diff.path || '')}
            >
              <Icon name="file" size={13} /> Open file
            </button>
          ) : null}
        </div>
      </div>

      {held && held.kind === 'diff' ? (
        <>
          <div className="review-grid changes-grid">
            <div className="review-files">
              <div className="review-files-head">
                <span>Proposed file</span>
                <span className="mono">{held.tool}</span>
              </div>
              <div className="file-list">
                <button type="button" className="file-item on">
                  <Icon name="file" size={13} />
                  <span className="fname">{held.relPath || held.path || 'file'}</span>
                  <span className="fstat">
                    {held.stats ? <><span className="add">+{held.stats.added}</span> <span className="del">−{held.stats.removed}</span></> : null}
                  </span>
                </button>
              </div>
              <div className="changes-risk">
                <Icon name="shield" size={14} />
                <span>
                  Approval releases this write once. The run stays inside its tier; the change is still
                  recorded in the audit chain.
                </span>
              </div>
            </div>
            <div className="review-diff">
              <div className="file-head">
                <Icon name="file" size={14} />
                <code>{held.relPath || held.path || 'proposed change'}</code>
                <span className="grow" />
                {editedAfter ? <span className="edited-tag">edited draft will be sent</span> : null}
              </div>
              <DiffViewer
                key={held.decisionId}
                before={held.before || ''}
                after={editedAfter ?? held.after ?? ''}
                rawDiff={held.rawDiff}
                hunks={held.hunks}
                stats={held.stats}
                editable
                onEdit={onEdit}
              />
            </div>
          </div>
          <p className="changes-note">
            Editing here changes the content that is released; it does not change the diff shown in the
            trace. The approval decision is still one decision for this one write.
          </p>
        </>
      ) : null}

      {held && held.kind !== 'diff' ? (
        <div className="approval-details">
          <h3>{held.summary || 'Approval requested'}</h3>
          <div className="summary">
            <b>{held.tool}</b>
            {held.kind === 'outside_root' ? ' wants to work outside the run workspace.' : ' wants to run a destructive action.'}
          </div>
          {held.absoluteTarget ? (
            <div className="target">
              <span className="muted">target </span>
              <code>{held.absoluteTarget}</code>
              {held.effectiveCwd ? (
                <>
                  <br />
                  <span className="muted">from </span>
                  <code>{held.effectiveCwd}</code>
                </>
              ) : null}
            </div>
          ) : null}
          <pre>{prettyArgs(held.args)}</pre>
          <p className="changes-note">
            {held.kind === 'outside_root'
              ? 'Outside-root actions are deliberately narrow: choose the one-time, session, or deny action at the gate.'
              : 'A destructive action needs an explicit human release. Denying it leaves the run paused, not failed.'}
          </p>
        </div>
      ) : null}

      {!held && diff ? (
        <div className="changes-resolved">
          <div className="file-head">
            <Icon name="check" size={14} />
            <code>{diff.relPath || diff.path || 'change'}</code>
            <span className="grow" />
            <span className="muted small">last proposed change</span>
          </div>
          <DiffViewer
            before={diff.before || ''}
            after={diff.after || ''}
            rawDiff={diff.rawDiff}
            hunks={diff.hunks}
            stats={diff.stats}
          />
        </div>
      ) : null}

      {!held && !diff ? (
        <div className="empty-panel">
          <Icon name="file" size={22} />
          <h3>Nothing to review yet</h3>
          <p>The Changes tab fills when the agent proposes an edit or asks to cross a boundary.</p>
        </div>
      ) : null}
    </div>
  )
}

function prettyArgs(args: unknown) {
  try {
    return JSON.stringify(args, null, 2)
  } catch {
    return String(args)
  }
}

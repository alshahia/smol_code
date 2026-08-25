// v1.9.x (decision 0025 sec 3.10 / B10 + decision 0027): mid-run
// "Auto-approve is ON" banner shown while a run has
// auto-approve-destructive enabled. Clicking Disable now reaches
// the BE via POST /api/runs/{id}/auto-approve (decision 0027) so
// the underlying session flag flips too -- future destructive
// prompts re-arm the ApprovalModal instead of being silently
// auto-approved.

import React from 'react'

export interface AutoApproveBannerProps {
  /** Active run id; null hides the banner. */
  runId: string | null
  /** Invoked when the user clicks Disable. */
  onDisable: () => void
}

export function AutoApproveBanner({ runId, onDisable }: AutoApproveBannerProps): React.JSX.Element | null {
  if (!runId) return null
  return (
    <div
      className="auto-approve-banner"
      role="status"
      data-testid="auto-approve-banner"
    >
      <span className="auto-approve-banner-text">
        Auto-approve is ON for this run &mdash; future approval prompts will be
        auto-granted.
      </span>
      <button
        type="button"
        className="btn btn-secondary auto-approve-banner-disable"
        onClick={onDisable}
        aria-label="Disable auto-approve"
      >
        Disable
      </button>
    </div>
  )
}

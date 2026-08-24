// Phase 3 (decision 0025 sec 6.5 / FE-2): per-run cost chip that
// renders USD cost for a run based on its tokens + provider/model.
// The cost is computed server-side and exposed via the Dashboard tab;
// this component is a small render-only display for the Inspector.

export interface CostBadgeProps {
  costUsd: number | null | undefined
  rateSource?: 'default' | 'override' | 'unknown'
  /** When true, show the breakdown tooltip (input/output/cache). */
  detailed?: boolean
}

function formatUsd(n: number): string {
  if (!isFinite(n)) return '--'
  if (n === 0) return '$0.00'
  if (n < 0.01) return '$' + n.toFixed(4)
  return '$' + n.toFixed(2)
}

export function CostBadge({ costUsd, rateSource = 'unknown', detailed = false }: CostBadgeProps): React.JSX.Element {
  const label = costUsd == null ? '--' : formatUsd(costUsd)
  const tooltip = rateSource === 'override'
    ? 'Cost uses your SMOLCODE_COST_RATES override.'
    : rateSource === 'default'
      ? 'Cost uses the built-in default rate for this provider/model.'
      : 'No rate configured for this provider/model — cost is unknown.'
  return (
    <span
      className={`cost-badge cost-badge-${rateSource}`}
      title={tooltip}
      aria-label={tooltip}
      data-testid="cost-badge"
    >
      {label}
      {detailed && rateSource !== 'unknown' && (
        <small className="cost-badge-source"> {rateSource}</small>
      )}
    </span>
  )
}
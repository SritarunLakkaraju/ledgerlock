import { formatInr, formatPct, reasonLabel } from '../format'
import type { Metrics } from '../types'

interface Props {
  metrics: Metrics
}

function Tile({ label, value, tone }: { label: string; value: string; tone?: 'accent' | 'danger' }) {
  const color = tone === 'accent' ? 'text-[var(--accent)]' : tone === 'danger' ? 'text-[var(--danger)]' : 'text-[var(--text)]'
  return (
    <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg)] px-4 py-3 flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wide text-[var(--text-faint)]">{label}</span>
      <span className={`font-num text-xl font-semibold ${color}`}>{value}</span>
    </div>
  )
}

export function MetricsVsTruthPanel({ metrics }: Props) {
  const reasons = Object.entries(metrics.exceptions_by_reason).sort((a, b) => b[1].amount_impact_paise - a[1].amount_impact_paise)
  const maxImpact = Math.max(1, ...reasons.map(([, v]) => v.amount_impact_paise))

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-6 flex flex-col gap-6">
      <div>
        <h2 className="text-sm uppercase tracking-wide text-[var(--text-faint)] mb-1">Measured against ground truth</h2>
        <p className="text-xs text-[var(--text-dim)]">
          Every number below is scored against the synthetic generator's ground truth, never self-reported by the engine.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Tile label="Precision" value={formatPct(metrics.precision)} />
        <Tile label="Recall" value={formatPct(metrics.recall)} />
        <Tile label="F1" value={formatPct(metrics.f1)} />
        <Tile label="Reason-code accuracy" value={formatPct(metrics.reason_code_accuracy)} />
        <Tile
          label="False matches"
          value={String(metrics.false_match_count)}
          tone={metrics.false_match_count > 0 ? 'danger' : 'accent'}
        />
      </div>

      {reasons.length > 0 && (
        <div>
          <h3 className="text-xs uppercase tracking-wide text-[var(--text-faint)] mb-3">Exceptions by reason</h3>
          <div className="flex flex-col gap-2">
            {reasons.map(([code, v]) => (
              <div key={code} className="flex items-center gap-3 text-xs">
                <span className="w-48 shrink-0 text-[var(--text-dim)] truncate">{reasonLabel(code)}</span>
                <div className="flex-1 h-2 rounded-full bg-[var(--bg)] overflow-hidden">
                  <div
                    className="h-full bg-[var(--danger)] rounded-full"
                    style={{ width: `${(v.amount_impact_paise / maxImpact) * 100}%` }}
                  />
                </div>
                <span className="font-num text-[var(--text-faint)] w-10 text-right">{v.count}</span>
                <span className="font-num text-[var(--text)] w-28 text-right">{formatInr(v.amount_impact_paise)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {metrics.rounding_drift_absorbed.count > 0 && (
        <div className="text-xs text-[var(--text-dim)]">
          <span className="text-[var(--accent)] font-medium">{metrics.rounding_drift_absorbed.count}</span> settlement
          {metrics.rounding_drift_absorbed.count === 1 ? '' : 's'} absorbed{' '}
          <span className="font-num">{formatInr(metrics.rounding_drift_absorbed.total_paise)}</span> of rounding drift within
          tolerance -- matched, not force-matched.
        </div>
      )}

      {metrics.throughput_records_per_sec != null && (
        <div className="text-xs text-[var(--text-faint)] font-num">
          {metrics.throughput_records_per_sec.toLocaleString('en-IN')} records/sec
        </div>
      )}
    </div>
  )
}

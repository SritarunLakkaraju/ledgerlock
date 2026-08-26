import { formatInr, formatPct } from '../format'
import type { ReconcileSummary } from '../types'

interface Props {
  summary: ReconcileSummary
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'accent' | 'danger' | 'default' }) {
  const color = tone === 'accent' ? 'text-[var(--accent)]' : tone === 'danger' ? 'text-[var(--danger)]' : 'text-[var(--text)]'
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs uppercase tracking-wide text-[var(--text-faint)]">{label}</span>
      <span className={`font-num text-4xl font-bold ${color}`}>{value}</span>
      {sub && <span className="text-xs text-[var(--text-dim)]">{sub}</span>}
    </div>
  )
}

export function HeroMetrics({ summary }: Props) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-8">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
        <Stat label="Auto-matched" value={formatPct(summary.auto_match_rate)} tone="accent" sub={`${summary.matched_count.toLocaleString('en-IN')} records`} />
        <Stat label="Flagged" value={summary.exception_count.toLocaleString('en-IN')} sub="need review" />
        <Stat
          label="False matches"
          value={summary.false_match_count.toLocaleString('en-IN')}
          tone={summary.false_match_count > 0 ? 'danger' : 'accent'}
          sub={summary.false_match_count === 0 ? 'zero-tolerance, met' : 'investigate immediately'}
        />
        <Stat label="Reconciled value" value={formatInr(summary.value_reconciled_paise)} sub={`${formatInr(summary.value_flagged_paise)} flagged`} />
      </div>
    </div>
  )
}

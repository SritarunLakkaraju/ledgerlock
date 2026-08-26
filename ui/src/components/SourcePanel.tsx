interface Props {
  title: string
  subtitle: string
  count: number | null
  accent: string
}

export function SourcePanel({ title, subtitle, count, accent }: Props) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-5 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-[var(--text-dim)] uppercase tracking-wide">{title}</span>
        <span className="h-2 w-2 rounded-full" style={{ background: accent }} />
      </div>
      <div className="font-num text-3xl font-semibold text-[var(--text)]">
        {count === null ? <span className="text-[var(--text-faint)]">—</span> : count.toLocaleString('en-IN')}
      </div>
      <div className="text-xs text-[var(--text-faint)]">{subtitle}</div>
    </div>
  )
}

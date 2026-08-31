interface Props {
  title: string
  subtitle: string
  count: number | null
  accent: string
  onClick?: () => void
  active?: boolean
}

export function SourcePanel({ title, subtitle, count, accent, onClick, active }: Props) {
  const clickable = !!onClick
  return (
    <div
      onClick={onClick}
      className={`rounded-lg border bg-[var(--bg-card)] p-5 flex flex-col gap-3 transition-colors ${
        active ? 'border-[var(--text-dim)]' : 'border-[var(--border)]'
      } ${clickable ? 'cursor-pointer hover:border-[var(--text-faint)]' : ''}`}
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-[var(--text-dim)] uppercase tracking-wide">{title}</span>
        <span className="h-2 w-2 rounded-full" style={{ background: accent }} />
      </div>
      <div className="font-num text-3xl font-semibold text-[var(--text)]">
        {count === null ? <span className="text-[var(--text-faint)]">—</span> : count.toLocaleString('en-IN')}
      </div>
      <div className="text-xs text-[var(--text-faint)]">{subtitle}</div>
      {clickable && (
        <div className="text-xs text-[var(--text-dim)] mt-1">{active ? 'Hide rows' : 'View rows →'}</div>
      )}
    </div>
  )
}

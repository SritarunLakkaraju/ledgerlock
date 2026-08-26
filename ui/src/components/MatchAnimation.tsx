interface Props {
  stage: 'A' | 'B' | 'C' | 'done'
}

const STAGES: { key: 'A' | 'B' | 'C'; label: string }[] = [
  { key: 'A', label: 'Order ↔ Payment' },
  { key: 'B', label: 'Settlement net' },
  { key: 'C', label: 'Settlement ↔ Bank' },
]

const STAGE_ORDER = { A: 0, B: 1, C: 2, done: 3 }

function Column({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center gap-2 w-28">
      <div className="h-16 w-16 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] flex items-center justify-center">
        <span className="h-3 w-3 rounded-full bg-[var(--accent)] animate-pulse" />
      </div>
      <span className="text-[11px] text-[var(--text-faint)] text-center leading-tight">{label}</span>
    </div>
  )
}

function Link({ active, done }: { active: boolean; done: boolean }) {
  const color = done ? 'var(--accent)' : active ? 'var(--warn)' : 'var(--border)'
  return (
    <svg width="80" height="16" className="shrink-0">
      <line
        x1="0"
        y1="8"
        x2="80"
        y2="8"
        stroke={color}
        strokeWidth="2"
        strokeDasharray={done ? undefined : '6 4'}
        className={active && !done ? 'animate-pulse' : ''}
      />
    </svg>
  )
}

export function MatchAnimation({ stage }: Props) {
  const idx = STAGE_ORDER[stage]
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-8 flex flex-col items-center gap-6">
      <div className="flex items-center">
        <Column label="Orders" />
        <Link active={idx >= 0} done={idx > 0} />
        <Column label="Razorpay recon" />
        <Link active={idx >= 1} done={idx > 1} />
        <Column label="Bank statement" />
      </div>
      <div className="flex gap-6">
        {STAGES.map((s) => {
          const state = idx > STAGE_ORDER[s.key] ? 'done' : idx === STAGE_ORDER[s.key] ? 'active' : 'pending'
          return (
            <div key={s.key} className="flex items-center gap-2 text-xs">
              <span
                className={`font-num font-semibold px-1.5 py-0.5 rounded ${
                  state === 'done'
                    ? 'text-[var(--accent)]'
                    : state === 'active'
                      ? 'text-[var(--warn)] animate-pulse'
                      : 'text-[var(--text-faint)]'
                }`}
              >
                {s.key}
              </span>
              <span className={state === 'pending' ? 'text-[var(--text-faint)]' : 'text-[var(--text-dim)]'}>{s.label}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

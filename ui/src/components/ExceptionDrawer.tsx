import { useEffect, useState } from 'react'
import { api } from '../api'
import { formatInr, reasonLabel } from '../format'
import type { ExceptionDetail } from '../types'

interface Props {
  runId: string
  exceptionId: string
  onClose: () => void
  resolved: boolean
  onToggleResolved: (id: string) => void
}

function KeyValueBlock({ title, data }: { title: string; data: Record<string, unknown> }) {
  const entries = Object.entries(data).filter(([k]) => k !== 'reason')
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-[var(--text-faint)] mb-1.5">{title}</div>
      <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg)] p-3 space-y-1">
        {entries.length === 0 && <span className="text-xs text-[var(--text-faint)]">—</span>}
        {entries.map(([k, v]) => (
          <div key={k} className="flex justify-between text-xs gap-4">
            <span className="text-[var(--text-faint)]">{k}</span>
            <span className="font-num text-[var(--text)] text-right break-all">
              {typeof v === 'number' && /paise/.test(k) ? formatInr(v) : String(v ?? '—')}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

const MAX_SOURCE_ROWS = 8

function SourceRowTable({ title, rows }: { title: string; rows: Record<string, unknown>[] }) {
  if (rows.length === 0) return null
  const cols = Object.keys(rows[0])
  const visible = rows.slice(0, MAX_SOURCE_ROWS)
  const hidden = rows.length - visible.length
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-[var(--text-faint)] mb-1.5">
        {title} <span className="text-[var(--text-faint)] normal-case">({rows.length})</span>
      </div>
      <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg)] overflow-x-auto">
        <table className="text-xs w-full">
          <thead>
            <tr className="border-b border-[var(--border-subtle)]">
              {cols.map((c) => (
                <th key={c} className="text-left px-2 py-1.5 text-[var(--text-faint)] whitespace-nowrap">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((r, i) => (
              <tr key={i} className="border-b border-[var(--border-subtle)] last:border-0">
                {cols.map((c) => (
                  <td key={c} className="px-2 py-1.5 font-num text-[var(--text)] whitespace-nowrap">
                    {String(r[c] ?? '')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {hidden > 0 && (
          <div className="px-2 py-1.5 text-[var(--text-faint)] border-t border-[var(--border-subtle)]">+{hidden} more row{hidden === 1 ? '' : 's'}</div>
        )}
      </div>
    </div>
  )
}

export function ExceptionDrawer({ runId, exceptionId, onClose, resolved, onToggleResolved }: Props) {
  const [detail, setDetail] = useState<ExceptionDetail | null>(null)
  const [explaining, setExplaining] = useState(false)

  useEffect(() => {
    setDetail(null)
    api.exceptionDetail(runId, exceptionId).then(setDetail)
  }, [runId, exceptionId])

  async function handleExplain() {
    setExplaining(true)
    try {
      const updated = await api.explain(runId, exceptionId)
      setDetail((d) => (d ? { ...d, ai: updated.ai } : d))
    } finally {
      setExplaining(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative w-full max-w-xl h-full bg-[var(--bg-elevated)] border-l border-[var(--border)] overflow-y-auto p-6 flex flex-col gap-6">
        <div className="flex items-start justify-between">
          <div>
            <div className="text-xs text-[var(--text-faint)] font-num">{exceptionId}</div>
            <h2 className="text-lg font-semibold mt-0.5">{detail ? reasonLabel(detail.reason_code) : '…'}</h2>
          </div>
          <button onClick={onClose} className="text-[var(--text-faint)] hover:text-[var(--text)] text-xl leading-none px-1">
            ×
          </button>
        </div>

        {!detail && <div className="text-sm text-[var(--text-faint)]">Loading…</div>}

        {detail && (
          <>
            <div className="flex flex-wrap gap-4 text-xs">
              <span className="font-num px-2 py-1 rounded bg-[var(--bg-card)] border border-[var(--border-subtle)]">Stage {detail.stage}</span>
              <span className="font-num px-2 py-1 rounded bg-[var(--bg-card)] border border-[var(--border-subtle)]">
                Impact {formatInr(detail.amount_impact_paise)}
              </span>
              <span className="font-num px-2 py-1 rounded bg-[var(--bg-card)] border border-[var(--border-subtle)]">
                Tolerance ±{formatInr(detail.tolerance_applied_paise)}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <KeyValueBlock title="Expected" data={detail.expected} />
              <KeyValueBlock title="Actual" data={detail.actual} />
            </div>

            <KeyValueBlock title="Entities" data={detail.entities} />

            <div>
              <div className="text-xs uppercase tracking-wide text-[var(--text-faint)] mb-1.5">Rule trace</div>
              <ol className="text-xs font-num text-[var(--text-dim)] space-y-1 list-decimal list-inside">
                {detail.rule_trace.map((t, i) => (
                  <li key={i}>{t}</li>
                ))}
              </ol>
            </div>

            {detail.source_rows.order && <SourceRowTable title="Order" rows={[detail.source_rows.order]} />}
            <SourceRowTable title="Recon rows" rows={detail.source_rows.recon_rows} />
            <SourceRowTable title="Bank rows" rows={detail.source_rows.bank_rows} />

            <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg)] p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs uppercase tracking-wide text-[var(--text-faint)]">AI explanation</span>
                {detail.ai && (
                  <span className="text-[10px] font-num text-[var(--text-faint)]">
                    {detail.ai.model} {detail.ai.cached && '· cached'}
                  </span>
                )}
              </div>
              {detail.ai ? (
                <div className="space-y-2">
                  <p className="text-sm text-[var(--text)]">{detail.ai.explanation}</p>
                  <p className="text-sm text-[var(--accent)]">→ {detail.ai.suggested_action}</p>
                </div>
              ) : (
                <button
                  onClick={handleExplain}
                  disabled={explaining}
                  className="text-sm text-[var(--accent)] hover:underline disabled:opacity-50"
                >
                  {explaining ? 'Explaining…' : 'Generate explanation'}
                </button>
              )}
            </div>

            <button
              onClick={() => onToggleResolved(exceptionId)}
              className={`self-start rounded-md px-4 py-2 text-sm font-medium transition-colors ${
                resolved
                  ? 'bg-[var(--bg-card)] text-[var(--text-dim)] border border-[var(--border)]'
                  : 'bg-[var(--accent)] text-[#06110d]'
              }`}
            >
              {resolved ? 'Marked resolved ✓' : 'Mark resolved'}
            </button>
          </>
        )}
      </div>
    </div>
  )
}

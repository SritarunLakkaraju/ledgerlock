import { useEffect, useState } from 'react'
import { api } from '../api'
import { formatInr } from '../format'
import type { SourceRows, SourceTable } from '../types'

interface Props {
  runId: string
  initialTable?: SourceTable
  onClose: () => void
}

const TABS: { key: SourceTable; label: string; file: string }[] = [
  { key: 'orders', label: 'Orders', file: 'orders.csv' },
  { key: 'recon', label: 'Razorpay recon', file: 'razorpay_recon.csv' },
  { key: 'bank', label: 'Bank statement', file: 'bank_statement.csv' },
]

const PAGE_SIZE = 100

function renderCell(col: string, value: unknown) {
  if (value === null || value === undefined || value === '') {
    return <span className="text-[var(--text-faint)]">—</span>
  }
  if (typeof value === 'boolean') {
    return value ? 'yes' : 'no'
  }
  if (col.endsWith('_paise') && typeof value === 'number') {
    return <span className="font-num">{formatInr(value)}</span>
  }
  if (typeof value === 'string' && value.includes('T') && /\d{4}-\d{2}-\d{2}T/.test(value)) {
    return value.replace('T', ' ').slice(0, 16)
  }
  return String(value)
}

export function SourceDataViewer({ runId, initialTable = 'orders', onClose }: Props) {
  const [table, setTable] = useState<SourceTable>(initialTable)
  const [page, setPage] = useState(1)
  const [data, setData] = useState<SourceRows | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setPage(1)
  }, [table])

  useEffect(() => {
    setLoading(true)
    api
      .sources(runId, table, page, PAGE_SIZE)
      .then(setData)
      .finally(() => setLoading(false))
  }, [runId, table, page])

  const total = data?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
  const to = Math.min(page * PAGE_SIZE, total)

  return (
    <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden">
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
        <div className="flex gap-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTable(t.key)}
              className={`text-sm px-3 py-1.5 rounded transition-colors ${
                table === t.key
                  ? 'bg-[var(--bg-elevated)] text-[var(--text)]'
                  : 'text-[var(--text-dim)] hover:text-[var(--text)]'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <button
          onClick={onClose}
          className="text-xs text-[var(--text-faint)] hover:text-[var(--text)]"
        >
          Hide
        </button>
      </div>

      <div className="px-4 py-2 text-xs text-[var(--text-faint)] border-b border-[var(--border-subtle)] flex items-center justify-between">
        <span>
          {TABS.find((t) => t.key === table)?.file} · {total.toLocaleString('en-IN')} rows
        </span>
        {total > PAGE_SIZE && (
          <span className="flex items-center gap-2">
            <button
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
              className="px-2 py-0.5 rounded disabled:opacity-30 hover:text-[var(--text)]"
            >
              ← prev
            </button>
            <span>
              {from.toLocaleString('en-IN')}–{to.toLocaleString('en-IN')}
            </span>
            <button
              disabled={page >= pageCount}
              onClick={() => setPage((p) => p + 1)}
              className="px-2 py-0.5 rounded disabled:opacity-30 hover:text-[var(--text)]"
            >
              next →
            </button>
          </span>
        )}
      </div>

      <div className="overflow-x-auto max-h-[28rem] overflow-y-auto">
        {loading || !data ? (
          <div className="text-sm text-[var(--text-faint)] py-10 text-center">Loading…</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-[var(--bg-card)]">
              <tr className="border-b border-[var(--border)]">
                {data.columns.map((c) => (
                  <th
                    key={c}
                    className="text-left px-3 py-2 text-xs uppercase tracking-wide text-[var(--text-faint)] whitespace-nowrap"
                  >
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.items.map((row, i) => (
                <tr key={i} className="border-b border-[var(--border-subtle)] hover:bg-[var(--bg-elevated)]">
                  {data.columns.map((c) => (
                    <td key={c} className="px-3 py-2 text-[var(--text)] whitespace-nowrap">
                      {renderCell(c, row[c])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}

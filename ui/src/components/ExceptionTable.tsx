import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { formatInr, reasonLabel } from '../format'
import type { ExceptionRecord } from '../types'

interface Props {
  runId: string
  onSelect: (exceptionId: string) => void
  selectedId: string | null
  resolved: Set<string>
}

type SortKey = 'reason_code' | 'amount_impact_paise' | 'stage'

const STAGE_COLOR: Record<string, string> = { A: 'var(--info)', B: 'var(--warn)', C: 'var(--danger)' }

export function ExceptionTable({ runId, onSelect, selectedId, resolved }: Props) {
  const [items, setItems] = useState<ExceptionRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [sortKey, setSortKey] = useState<SortKey>('amount_impact_paise')
  const [sortDir, setSortDir] = useState<1 | -1>(-1)

  useEffect(() => {
    setLoading(true)
    api
      .exceptions(runId)
      .then((r) => setItems(r.items))
      .finally(() => setLoading(false))
  }, [runId])

  const sorted = useMemo(() => {
    const copy = [...items]
    copy.sort((a, b) => {
      const av = a[sortKey]
      const bv = b[sortKey]
      const cmp = typeof av === 'number' && typeof bv === 'number' ? av - bv : String(av).localeCompare(String(bv))
      return cmp * sortDir
    })
    return copy
  }, [items, sortKey, sortDir])

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDir((d) => (d === 1 ? -1 : 1))
    else {
      setSortKey(key)
      setSortDir(-1)
    }
  }

  if (loading) {
    return <div className="text-sm text-[var(--text-faint)] py-8 text-center">Loading exceptions…</div>
  }

  if (items.length === 0) {
    return (
      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-8 text-center text-sm text-[var(--text-dim)]">
        No exceptions on this run.
      </div>
    )
  }

  const Header = ({ label, k }: { label: string; k: SortKey }) => (
    <th
      className="text-left px-4 py-3 text-xs uppercase tracking-wide text-[var(--text-faint)] cursor-pointer select-none hover:text-[var(--text-dim)]"
      onClick={() => toggleSort(k)}
    >
      {label} {sortKey === k && (sortDir === 1 ? '↑' : '↓')}
    </th>
  )

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden">
      <table className="w-full text-sm">
        <thead className="border-b border-[var(--border)]">
          <tr>
            <th className="text-left px-4 py-3 text-xs uppercase tracking-wide text-[var(--text-faint)]">Stage</th>
            <Header label="Reason" k="reason_code" />
            <Header label="Impact" k="amount_impact_paise" />
            <th className="text-left px-4 py-3 text-xs uppercase tracking-wide text-[var(--text-faint)]">Status</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((exc) => (
            <tr
              key={exc.exception_id}
              onClick={() => onSelect(exc.exception_id)}
              className={`border-b border-[var(--border-subtle)] cursor-pointer transition-colors hover:bg-[var(--bg-elevated)] ${
                selectedId === exc.exception_id ? 'bg-[var(--bg-elevated)]' : ''
              }`}
            >
              <td className="px-4 py-3">
                <span
                  className="font-num text-xs font-semibold px-1.5 py-0.5 rounded"
                  style={{ color: STAGE_COLOR[exc.stage], background: 'color-mix(in srgb, ' + STAGE_COLOR[exc.stage] + ' 15%, transparent)' }}
                >
                  {exc.stage}
                </span>
              </td>
              <td className="px-4 py-3 text-[var(--text)]">{reasonLabel(exc.reason_code)}</td>
              <td className="px-4 py-3 font-num text-[var(--text)]">{formatInr(exc.amount_impact_paise)}</td>
              <td className="px-4 py-3">
                {resolved.has(exc.exception_id) ? (
                  <span className="text-xs text-[var(--accent)]">Resolved</span>
                ) : (
                  <span className="text-xs text-[var(--text-faint)]">Open</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

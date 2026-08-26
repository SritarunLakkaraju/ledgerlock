import { useRef, useState } from 'react'
import { api } from './api'
import { ExceptionDrawer } from './components/ExceptionDrawer'
import { ExceptionTable } from './components/ExceptionTable'
import { HeroMetrics } from './components/HeroMetrics'
import { MatchAnimation } from './components/MatchAnimation'
import { MetricsVsTruthPanel } from './components/MetricsVsTruthPanel'
import { RunButton } from './components/RunButton'
import { SourcePanel } from './components/SourcePanel'
import type { GenerateCounts, Metrics, ReconcileSummary } from './types'

type Status = 'idle' | 'generating' | 'reconciling' | 'done' | 'error'
type AnimStage = 'A' | 'B' | 'C' | 'done'

export default function App() {
  const [status, setStatus] = useState<Status>('idle')
  const [runId, setRunId] = useState<string | null>(null)
  const [counts, setCounts] = useState<GenerateCounts | null>(null)
  const [summary, setSummary] = useState<ReconcileSummary | null>(null)
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedExceptionId, setSelectedExceptionId] = useState<string | null>(null)
  const [resolved, setResolved] = useState<Set<string>>(new Set())
  const [animStage, setAnimStage] = useState<AnimStage>('A')
  const animTimers = useRef<ReturnType<typeof setTimeout>[]>([])

  function clearAnimTimers() {
    animTimers.current.forEach(clearTimeout)
    animTimers.current = []
  }

  async function handleRun() {
    setError(null)
    setSummary(null)
    setMetrics(null)
    setSelectedExceptionId(null)
    setResolved(new Set())
    clearAnimTimers()
    try {
      setStatus('generating')
      const seed = Math.floor(Math.random() * 1_000_000)
      const gen = await api.generate(seed)
      setRunId(gen.run_id)
      setCounts(gen.counts)

      setStatus('reconciling')
      setAnimStage('A')
      // Reconcile is a single backend call -- stage the animation over it so
      // the "locking" progression (SS9) reads as A -> B -> C rather than an
      // instant jump, independent of actual response latency.
      animTimers.current.push(setTimeout(() => setAnimStage('B'), 500))
      animTimers.current.push(setTimeout(() => setAnimStage('C'), 1000))
      const [rec] = await Promise.all([api.reconcile(gen.run_id), new Promise((r) => setTimeout(r, 1400))])
      clearAnimTimers()
      setAnimStage('done')
      setSummary(rec.summary)
      setMetrics(rec.metrics)
      setStatus('done')
    } catch (e) {
      clearAnimTimers()
      setError(e instanceof Error ? e.message : String(e))
      setStatus('error')
    }
  }

  function toggleResolved(id: string) {
    setResolved((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="min-h-full max-w-6xl mx-auto px-6 py-10 flex flex-col gap-8">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">LedgerLock</h1>
          <p className="text-sm text-[var(--text-dim)] mt-1">AI three-way settlement reconciler · Razorpay Buildathon</p>
        </div>
        <div className="flex items-center gap-3">
          {runId && status === 'done' && (
            <a
              href={api.exportCsvUrl(runId)}
              className="text-sm text-[var(--text-dim)] hover:text-[var(--text)] underline underline-offset-2"
            >
              Export exceptions CSV
            </a>
          )}
          <RunButton status={status} onRun={handleRun} />
        </div>
      </header>

      {error && (
        <div className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger-dim)] px-4 py-3 text-sm text-[var(--danger)]">
          {error}
        </div>
      )}

      <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <SourcePanel title="Orders" subtitle="merchant system of record" count={counts?.orders ?? null} accent="var(--info)" />
        <SourcePanel
          title="Razorpay recon"
          subtitle={counts ? `${counts.payments + counts.refunds + counts.adjustments} txns across ${counts.settlements} settlements` : 'payment, refund & adjustment rows'}
          count={counts ? counts.payments + counts.refunds + counts.adjustments : null}
          accent="var(--warn)"
        />
        <SourcePanel title="Bank statement" subtitle="credit rows, keyed by UTR" count={counts?.bank_rows ?? null} accent="var(--accent)" />
      </section>

      {status === 'reconciling' && <MatchAnimation stage={animStage} />}

      {summary && (
        <>
          <HeroMetrics summary={summary} />
          {metrics && <MetricsVsTruthPanel metrics={metrics} />}
          <section>
            <h2 className="text-sm uppercase tracking-wide text-[var(--text-faint)] mb-3">Exceptions</h2>
            {runId && (
              <ExceptionTable runId={runId} onSelect={setSelectedExceptionId} selectedId={selectedExceptionId} resolved={resolved} />
            )}
          </section>
        </>
      )}

      {runId && selectedExceptionId && (
        <ExceptionDrawer
          runId={runId}
          exceptionId={selectedExceptionId}
          onClose={() => setSelectedExceptionId(null)}
          resolved={resolved.has(selectedExceptionId)}
          onToggleResolved={toggleResolved}
        />
      )}
    </div>
  )
}

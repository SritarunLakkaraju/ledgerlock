interface Props {
  status: 'idle' | 'generating' | 'reconciling' | 'done' | 'error'
  onRun: () => void
}

const LABEL: Record<Props['status'], string> = {
  idle: 'Generate & Reconcile',
  generating: 'Generating synthetic data…',
  reconciling: 'Reconciling…',
  done: 'Run again (new seed)',
  error: 'Retry',
}

export function RunButton({ status, onRun }: Props) {
  const busy = status === 'generating' || status === 'reconciling'
  return (
    <button
      onClick={onRun}
      disabled={busy}
      className="rounded-md bg-[var(--accent)] text-[#06110d] font-semibold px-5 py-2.5 text-sm
                 hover:brightness-110 active:brightness-95 disabled:opacity-60 disabled:cursor-not-allowed
                 transition-all flex items-center gap-2"
    >
      {busy && (
        <span className="h-3.5 w-3.5 rounded-full border-2 border-[#06110d]/30 border-t-[#06110d] animate-spin" />
      )}
      {LABEL[status]}
    </button>
  )
}

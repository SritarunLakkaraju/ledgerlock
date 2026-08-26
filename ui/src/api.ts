import type {
  ExceptionDetail,
  GenerateResponse,
  PaginatedExceptions,
  PaginatedMatches,
  ReconcileResponse,
} from './types'

const BASE = '/api'

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  generate: (seed?: number, n_orders?: number) =>
    fetch(`${BASE}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ seed, n_orders }),
    }).then((r) => j<GenerateResponse>(r)),

  reconcile: (runId: string) =>
    fetch(`${BASE}/reconcile/${runId}`, { method: 'POST' }).then((r) => j<ReconcileResponse>(r)),

  exceptions: (runId: string, reason?: string, page = 1) => {
    const params = new URLSearchParams({ page: String(page) })
    if (reason) params.set('reason', reason)
    return fetch(`${BASE}/runs/${runId}/exceptions?${params}`).then((r) => j<PaginatedExceptions>(r))
  },

  exceptionDetail: (runId: string, exceptionId: string) =>
    fetch(`${BASE}/runs/${runId}/exceptions/${exceptionId}`).then((r) => j<ExceptionDetail>(r)),

  matches: (runId: string, stage?: string, page = 1) => {
    const params = new URLSearchParams({ page: String(page) })
    if (stage) params.set('stage', stage)
    return fetch(`${BASE}/runs/${runId}/matches?${params}`).then((r) => j<PaginatedMatches>(r))
  },

  explain: (runId: string, exceptionId: string) =>
    fetch(`${BASE}/runs/${runId}/explain/${exceptionId}`, { method: 'POST' }).then((r) => j<ExceptionDetail>(r)),

  exportCsvUrl: (runId: string) => `${BASE}/runs/${runId}/export.csv`,
}

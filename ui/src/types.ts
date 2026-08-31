export interface GenerateCounts {
  orders: number
  payments: number
  refunds: number
  adjustments: number
  settlements: number
  bank_rows: number
  ground_truth_entities: number
}

export interface GenerateResponse {
  run_id: string
  counts: GenerateCounts
}

export interface Metrics {
  auto_match_rate: number
  precision: number
  recall: number
  f1: number
  false_match_count: number
  true_positive_count: number
  false_negative_count: number
  true_negative_count: number
  total_entities_evaluated: number
  matched_count: number
  exceptions_by_reason: Record<string, { count: number; amount_impact_paise: number }>
  value_reconciled_paise: number
  value_flagged_paise: number
  rounding_drift_absorbed: { count: number; total_paise: number }
  reason_code_accuracy: number
  throughput_records_per_sec: number | null
}

export interface ReconcileSummary {
  auto_match_rate: number
  matched_count: number
  exception_count: number
  false_match_count: number
  value_reconciled_paise: number
  value_flagged_paise: number
  stage_counts: Record<string, number>
}

export interface ReconcileResponse {
  metrics: Metrics
  summary: ReconcileSummary
}

export interface AIExplanation {
  explanation: string
  suggested_action: string
  model: string
  cached: boolean
}

export interface ExceptionRecord {
  exception_id: string
  stage: 'A' | 'B' | 'C'
  reason_code: string
  entities: Record<string, unknown>
  expected: Record<string, unknown>
  actual: Record<string, unknown>
  amount_impact_paise: number
  tolerance_applied_paise: number
  rule_trace: string[]
  is_reconcilable: boolean
  ai: AIExplanation | null
}

export interface ExceptionDetail extends ExceptionRecord {
  source_rows: {
    order: Record<string, unknown> | null
    recon_rows: Record<string, unknown>[]
    bank_rows: Record<string, unknown>[]
  }
}

export interface MatchRecord {
  stage: 'A' | 'B' | 'C'
  entity_id: string
  reason_code: string
  tags: string[]
  details: Record<string, unknown>
}

export interface PaginatedExceptions {
  page: number
  page_size: number
  total: number
  items: ExceptionRecord[]
}

export interface PaginatedMatches {
  page: number
  page_size: number
  total: number
  items: MatchRecord[]
}

export type SourceTable = 'orders' | 'recon' | 'bank'

export interface SourceRows {
  table: SourceTable
  page: number
  page_size: number
  total: number
  columns: string[]
  items: Record<string, unknown>[]
}

import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export const API = {
  base: API_BASE_URL,

  // Analysis endpoints
  analyze: async (data: AnalysisRequest) => {
    console.log('[API] Starting analyze request to:', `${API_BASE_URL}/api/analysis/analyze`)
    console.log('[API] Request data:', data)

    let response: Response
    try {
      response = await fetch(`${API_BASE_URL}/api/analysis/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      console.log('[API] Response status:', response.status, response.statusText)
    } catch (fetchError) {
      console.error('[API] Fetch error:', fetchError)
      throw new Error(`Network error: ${fetchError instanceof Error ? fetchError.message : 'Failed to connect to server'}`)
    }

    if (!response.ok) {
      let errorMessage = 'Analysis request failed'
      try {
        const error = await response.json()
        console.error('[API] Error response:', error)
        if (typeof error.detail === 'string') {
          errorMessage = error.detail
        } else if (error.message) {
          errorMessage = error.message
        } else {
          errorMessage = `HTTP ${response.status}: ${response.statusText}`
        }
      } catch (parseError) {
        console.error('[API] Error parsing error response:', parseError)
        errorMessage = `HTTP ${response.status}: ${response.statusText}`
      }
      throw new Error(errorMessage)
    }

    const result = await response.json() as Promise<AnalysisResponse>
    console.log('[API] Success response:', result)
    return result
  },

  analyzeSync: async (data: AnalysisRequest) => {
    const response = await fetch(`${API_BASE_URL}/api/analysis/analyze/sync`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!response.ok) throw new Error('Sync analysis failed')
    return response.json() as Promise<AnalysisResultResponse>
  },

  getWorkflowStatus: async (threadId: string) => {
    const response = await fetch(`${API_BASE_URL}/api/analysis/workflow/${threadId}`)
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Failed to get workflow status' }))
      const message = typeof error.detail === 'string' ? error.detail : 'Failed to get workflow status'
      throw new Error(message)
    }
    return response.json() as Promise<WorkflowStatusResponse>
  },

  getAnalysisResult: async (threadId: string) => {
    const response = await fetch(`${API_BASE_URL}/api/analysis/result/${threadId}`)
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Failed to get analysis result' }))
      const message = typeof error.detail === 'string' ? error.detail : 'Failed to get analysis result'
      throw new Error(message)
    }
    return response.json()
  },

  // Backtest endpoints
  runBacktest: async (data: BacktestRequest) => {
    const response = await fetch(`${API_BASE_URL}/api/backtest/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!response.ok) throw new Error('Backtest failed')
    return response.json() as Promise<BacktestResponse>
  },

  getStrategies: async () => {
    const response = await fetch(`${API_BASE_URL}/api/backtest/strategies`)
    if (!response.ok) throw new Error('Failed to get strategies')
    return response.json() as Promise<StrategiesResponse>
  },

  runWalkForward: async (data: WalkForwardRequest) => {
    const response = await fetch(`${API_BASE_URL}/api/backtest/v2/walkforward`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Walk-forward failed' }))
      const message = typeof error.detail === 'string' ? error.detail : 'Walk-forward failed'
      throw new Error(message)
    }
    return response.json() as Promise<WalkForwardResponse>
  },

  calibrateSignals: async (data: CalibrateRequest) => {
    const response = await fetch(`${API_BASE_URL}/api/backtest/v2/calibrate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Calibration failed' }))
      const message = typeof error.detail === 'string' ? error.detail : 'Calibration failed'
      throw new Error(message)
    }
    return response.json() as Promise<CalibrateResponse>
  },

  // Decision-layer signal quality endpoints
  getDecisionIC: async (horizonBars = 20) => {
    const response = await fetch(`${API_BASE_URL}/api/history/ic?horizon_bars=${horizonBars}`)
    if (!response.ok) throw new Error('Failed to get decision IC')
    return response.json() as Promise<DecisionICResponse>
  },

  getDecisionICDecay: async () => {
    const response = await fetch(`${API_BASE_URL}/api/history/ic/decay`)
    if (!response.ok) throw new Error('Failed to get IC decay')
    return response.json() as Promise<ICDecayResponse>
  },

  getRegimeConditionalIC: async (horizonBars = 20) => {
    const response = await fetch(
      `${API_BASE_URL}/api/history/ic/regime?horizon_bars=${horizonBars}`
    )
    if (!response.ok) throw new Error('Failed to get regime-conditional IC')
    return response.json() as Promise<RegimeConditionalICResponse>
  },

  getConfidenceCalibration: async (horizonBars = 20) => {
    const response = await fetch(
      `${API_BASE_URL}/api/history/ic/calibration?horizon_bars=${horizonBars}`
    )
    if (!response.ok) throw new Error('Failed to get confidence calibration')
    return response.json() as Promise<ConfidenceCalibrationResponse>
  },

  getTopKPortfolio: async (horizonBars = 20, topK = 1) => {
    const response = await fetch(
      `${API_BASE_URL}/api/history/portfolio?horizon_bars=${horizonBars}&top_k=${topK}`
    )
    if (!response.ok) throw new Error('Failed to get top-k portfolio')
    return response.json() as Promise<TopKPortfolioResponse>
  },

  // Monitoring endpoints
  getHealth: async () => {
    const response = await fetch(`${API_BASE_URL}/api/monitoring/health`)
    if (!response.ok) throw new Error('Failed to get health')
    return response.json() as Promise<SystemHealth>
  },

  getDataSourceHealth: async () => {
    const response = await fetch(`${API_BASE_URL}/api/monitoring/data-sources`)
    if (!response.ok) throw new Error('Failed to get data source health')
    return response.json() as Promise<DataSourceHealthResponse>
  },

  getMetrics: async (agentName?: string) => {
    const response = await fetch(
      `${API_BASE_URL}/api/monitoring/metrics${agentName ? `?agent_name=${agentName}` : ''}`
    )
    if (!response.ok) throw new Error('Failed to get metrics')
    return response.json()
  },

  getCircuitBreakers: async () => {
    const response = await fetch(`${API_BASE_URL}/api/monitoring/circuit-breakers`)
    if (!response.ok) throw new Error('Failed to get circuit breakers')
    return response.json() as Promise<CircuitBreakersResponse>
  },

  getEvents: async (agentName?: string, eventType?: string, limit = 100) => {
    const params = new URLSearchParams({ limit: limit.toString() })
    if (agentName) params.set('agent_name', agentName)
    if (eventType) params.set('event_type', eventType)
    const response = await fetch(
      `${API_BASE_URL}/api/monitoring/events?${params.toString()}`
    )
    if (!response.ok) throw new Error('Failed to get events')
    return response.json() as Promise<EventsResponse>
  },

  getAlerts: async (severity?: string, agentName?: string, activeOnly = true, limit = 50) => {
    const params = new URLSearchParams({
      active_only: activeOnly.toString(),
      limit: limit.toString(),
    })
    if (severity) params.set('severity', severity)
    if (agentName) params.set('agent_name', agentName)
    const response = await fetch(
      `${API_BASE_URL}/api/monitoring/alerts?${params.toString()}`
    )
    if (!response.ok) throw new Error('Failed to get alerts')
    return response.json() as Promise<AlertsResponse>
  },

  getRetryStats: async () => {
    const response = await fetch(`${API_BASE_URL}/api/monitoring/retry/stats`)
    if (!response.ok) throw new Error('Failed to get retry stats')
    return response.json() as Promise<RetryStatsResponse>
  },

  getTimeoutStats: async () => {
    const response = await fetch(`${API_BASE_URL}/api/monitoring/timeout/stats`)
    if (!response.ok) throw new Error('Failed to get timeout stats')
    return response.json() as Promise<TimeoutStatsResponse>
  },

  resetCircuitBreaker: async (name?: string) => {
    const response = await fetch(`${API_BASE_URL}/api/monitoring/circuit-breakers/reset`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(name ? { name } : {}),
    })
    if (!response.ok) throw new Error('Failed to reset circuit breaker')
    return response.json()
  },

  // ReAct Agent endpoints
  reactAnalyze: async (data: ReactAnalyzeRequest) => {
    const response = await fetch(`${API_BASE_URL}/api/agent/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Failed to start ReAct analysis' }))
      throw new Error(typeof error.detail === 'string' ? error.detail : 'Failed to start ReAct analysis')
    }
    return response.json() as Promise<ReactAnalyzeResponse>
  },

  getReactProgress: async (threadId: string) => {
    const response = await fetch(`${API_BASE_URL}/api/agent/progress/${threadId}`)
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Failed to get progress' }))
      throw new Error(typeof error.detail === 'string' ? error.detail : 'Failed to get progress')
    }
    return response.json() as Promise<ReactProgressResponse>
  },

  getReactResult: async (threadId: string) => {
    const response = await fetch(`${API_BASE_URL}/api/agent/result/${threadId}`)
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Failed to get result' }))
      throw new Error(typeof error.detail === 'string' ? error.detail : 'Failed to get result')
    }
    return response.json() as Promise<ReactResultResponse>
  },
}

// Type definitions
export interface AnalysisRequest {
  query: string
  symbols: string[]
  max_retries?: number
  timeout_per_agent?: number
  parallel_execution?: boolean
}

export interface AnalysisResponse {
  thread_id: string
  status: string
  message: string
  report_url?: string
}

export interface WorkflowStatusResponse {
  thread_id: string
  current_step: number
  current_agent: string | null
  agent_status: Record<string, string>
  has_errors: boolean
  is_complete: boolean
}

export interface AnalysisResultResponse {
  thread_id: string
  query: string
  symbols: string[]
  technical_analysis: any
  fundamental_analysis: any
  sentiment_analysis: any
  risk_assessment: any
  decisions: any
  report: any
  execution_time: number
  timestamp: string
}

export interface BacktestRequest {
  symbol: string
  strategy: 'sma_crossover' | 'rsi_strategy' | 'buy_and_hold' | 'macd_strategy' | 'technical_score'
  start_date: string
  end_date: string
  initial_cash?: number
  commission?: number
  sma_short?: number
  sma_long?: number
  rsi_period?: number
  rsi_overbought?: number
  rsi_oversold?: number
  fast_period?: number
  slow_period?: number
  signal_period?: number
  score_threshold?: number
}

export interface NullBenchmark {
  method: string
  iterations: number
  seed: number
  segments: number
  matched_round_trips: number
  strategy_return: number
  null_return_mean: number
  null_return_std: number
  null_return_p05: number
  null_return_p50: number
  null_return_p95: number
  percentile: number
  p_value: number
}

export interface BacktestResponse {
  symbol: string
  strategy: string
  period: { start: string; end: string }
  initial_cash: number
  final_value: number
  total_return: number
  total_return_pct: number
  annual_return: number
  sharpe_ratio: number
  max_drawdown: number
  win_rate: number
  total_trades: number
  equity: Array<{ date: string; value: number }>
  null_benchmark?: NullBenchmark | null
  execution_time: number
}

export interface DeflatedSharpe {
  status: string
  dsr: number
  sharpe_annualized: number
  sr0_annualized: number
  n_trials: number
  trial_sharpe_std_annualized: number
  oos_bars: number
  skew: number
  kurtosis: number
}

export interface WalkForwardWindow {
  test_start: string
  test_end: string
  chosen_params: Record<string, number>
  train_score: number | null
  train_results: Array<{
    params: Record<string, number>
    score: number | null
    sharpe: number | null
  }>
  test_metrics: Record<string, number | null>
  test_return: number | null
}

export interface WalkForwardAggregate {
  windows_run: number
  oos_return_mean: number | null
  oos_sharpe_mean: number | null
  losing_windows: number
  worst_window: { test_start: string; test_end: string; test_return: number } | null
  param_stability: number | null
  deflated_sharpe: DeflatedSharpe | null
  error?: string
}

export interface WalkForwardRequest {
  symbol: string
  strategy: 'sma_crossover' | 'rsi_strategy' | 'macd_strategy' | 'technical_score'
  start_date: string
  end_date: string
  param_grid: Record<string, number[]>
  train_bars: number
  test_bars: number
  initial_cash?: number
  market?: 'us' | 'cn'
  selection_metric?: 'sharpe' | 'cagr'
}

export interface WalkForwardResponse {
  windows: WalkForwardWindow[]
  aggregate: WalkForwardAggregate
  configs_tested: number
  manifest?: Record<string, unknown>
  execution_time?: number
}

export interface CalibrationHorizon {
  events: number
  hit_rate: number | null
  wilson_lower: number | null
  avg_forward_return?: number
  by_year: Record<string, { events: number; hit_rate: number }>
}

export interface CalibrateRequest {
  symbol: string
  strategy: 'sma_crossover' | 'rsi_strategy' | 'macd_strategy' | 'technical_score'
  start_date: string
  end_date: string
  horizons?: number[]
  benchmark_symbol?: string | null
  strategy_params?: Record<string, number>
}

export interface CalibrateResponse {
  strategy: string
  params: Record<string, number>
  entries_total: number
  by_horizon: Record<string, CalibrationHorizon>
  manifest?: Record<string, unknown>
  execution_time?: number
}

export interface StrategiesResponse {
  strategies: Array<{
    name: string
    description: string
    parameters: Record<string, string>
  }>
}

export interface DimensionSummary {
  runs: number
  ic_mean: number
  ic_std: number | null
  icir: number | null
  t_stat: number | null
  // Newey-West HAC t: prices the autocorrelation overlapping forward
  // windows introduce; null when not estimable (or absent pre-correction).
  t_stat_nw?: number | null
  ic_positive_rate: number
}

export interface DecisionICResponse {
  method: string
  horizon_bars: number
  records_examined: number
  runs_evaluated: number
  runs_pending_maturity: number
  runs_skipped: number
  per_run: Array<{
    thread_id: string
    date: string
    symbols: number
    ic: number
    regime_trend?: string | null
  }>
  dimensions?: Record<string, DimensionSummary | null>
  caveat: string
  status: 'ok' | 'insufficient_history'
  runs?: number
  ic_mean?: number
  ic_std?: number | null
  icir?: number | null
  t_stat?: number | null
  t_stat_nw?: number | null
  ic_positive_rate?: number
  execution_time?: number
}

export interface ICDecayPoint extends Omit<DecisionICResponse, 'dimensions'> {}

export interface ICDecayResponse {
  method: string
  horizons: ICDecayPoint[]
  status: 'ok' | 'insufficient_history'
  caveat: string
  execution_time?: number
}

export interface RegimeBinSummary {
  runs: number
  ic_mean?: number
  ic_std?: number | null
  icir?: number | null
  t_stat?: number | null
  t_stat_nw?: number | null
  ic_positive_rate?: number
  status: 'ok' | 'insufficient_history'
}

export interface RegimeConditionalICResponse {
  method: string
  horizon_bars: number
  records_examined: number
  runs_evaluated: number
  runs_pending_maturity: number
  runs_skipped: number
  runs_duplicate: number
  regimes: Record<'bull' | 'bear' | 'neutral' | 'unknown', RegimeBinSummary>
  status: 'ok' | 'insufficient_history'
  caveat: string
  regime_caveat: string
  execution_time?: number
}

export interface ReliabilityBin {
  bin_low: number
  bin_high: number
  n: number
  avg_confidence: number
  empirical_rate: number
}

export interface ConfidenceCalibrationResponse {
  method: string
  horizon_bars: number
  records_examined: number
  runs_evaluated: number
  runs_pending_maturity: number
  runs_skipped: number
  runs_duplicate?: number
  caveat: string
  status: 'ok' | 'insufficient_history'
  predictions?: number
  base_rate?: number
  avg_confidence?: number
  brier_score?: number | null
  brier_skill_score?: number | null
  reliability?: ReliabilityBin[]
  execution_time?: number
}

export interface TopKPortfolioResponse {
  method: string
  top_k: number
  horizon_bars: number
  records_examined: number
  runs_evaluated: number
  runs_pending_maturity: number
  runs_skipped: number
  runs_duplicate: number
  runs_narrow: number
  caveat: string
  status: 'ok' | 'insufficient_history'
  excess_mean?: number
  excess_std?: number | null
  excess_t_stat?: number | null
  // Newey-West HAC t over the per-run excesses (null below 3 runs).
  excess_t_stat_nw?: number | null
  hit_rate?: number
  per_run: Array<{
    thread_id: string
    date: string
    symbols: number
    top_return: number
    baseline_return: number
    excess: number
    regime_trend?: string | null
  }>
  execution_time?: number
}

// Per-provider outcome counters for the data chain's fallback seams.
// In-process state: providers appear only after their first recorded call,
// and every counter resets when the backend process restarts.
export interface ProviderHealthStats {
  total_calls: number
  ok: number
  fail: number
  fallback: number
  last_ok_at: string | null
  last_error: string | null
  last_error_at: string | null
}

export interface DataSourceHealthResponse {
  providers: Record<string, ProviderHealthStats>
  generated_at: string
}

// System-wide agent monitor overview (GET /api/monitoring/health — the
// monitor's get_system_overview). In-process counters: agents appear as they
// register executions, and everything resets when the backend restarts.
export interface SystemHealth {
  timestamp: string
  total_agents: number
  total_executions: number
  total_successful: number
  total_failed: number
  total_timeout: number
  overall_success_rate: number
  avg_health_score: number
  agents_health: Record<string, number>
  unhealthy_agents: string[]
  recent_events: MonitorEvent[]
  active_alerts: MonitorAlert[]
}

export interface MonitorEvent {
  event_type: string
  agent: string
  timestamp: string
  data?: Record<string, unknown>
}

export interface MonitorAlert {
  alert_id: string
  severity: 'low' | 'medium' | 'high' | 'critical'
  type: string
  agent: string
  message: string
  timestamp: string
  metadata?: Record<string, unknown>
}

// Per-agent circuit breaker state (GET /api/monitoring/circuit-breakers —
// registry.get_all_stats). failure_rate is a 0-1 fraction.
export interface CircuitBreakerStats {
  name: string
  state: 'CLOSED' | 'OPEN' | 'HALF_OPEN'
  total_calls: number
  successful_calls: number
  failed_calls: number
  failure_rate: number
  last_failure_time: string | null
  last_state_change: string | null
  opened_count: number
  config: { failure_threshold: number; success_threshold: number; timeout: number }
}

export interface CircuitBreakersResponse {
  [agentName: string]: CircuitBreakerStats
}

// Retry manager statistics (GET /api/monitoring/retry/stats). success_rate /
// avg_delay are absent when the retry history is empty (flat-zero shape).
export interface RetryStatsResponse {
  total_retries: number
  successful_retries: number
  failed_retries: number
  success_rate?: number
  avg_attempts: number
  total_delay: number
  avg_delay?: number
}

// Per-operation timeout statistics (GET /api/monitoring/timeout/stats).
// timeout_rate is a 0-1 fraction.
export interface TimeoutStatsResponse {
  [operation: string]: {
    total_calls: number
    completed_calls: number
    timeout_calls: number
    error_calls: number
    avg_execution_time: number
    max_execution_time: number
    timeout_rate: number
  }
}

export interface EventsResponse {
  events: Array<{
    timestamp: string
    agent_name: string
    event_type: string
    data?: any
  }>
}

export interface AlertsResponse {
  alerts: Array<{
    id: string
    severity: 'low' | 'medium' | 'high' | 'critical'
    agent_name: string
    message: string
    timestamp: string
    resolved: boolean
  }>
}

// ReAct Agent types
export interface ReactAnalyzeRequest {
  query: string
  symbols: string[]
  max_iterations?: number
}

export interface ReactAnalyzeResponse {
  thread_id: string
  status: string
}

export interface ReactProgressResponse {
  thread_id: string
  status: 'processing' | 'completed' | 'failed'
  iteration: number
  max_iterations: number
  tools_used: string[]
  tool_call_history: Array<{
    tool: string
    args: Record<string, any>
    status: string
  }>
  current_step: string
  started_at: string | null
  completed_at: string | null
}

export interface ReactResultResponse {
  answer: string
  report: Record<string, any> | null
  iterations: number
  tools_used: string[]
  cost: number
}

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

  getSymbolData: async (symbol: string) => {
    const response = await fetch(`${API_BASE_URL}/api/analysis/symbols/${symbol}`)
    if (!response.ok) throw new Error('Failed to get symbol data')
    return response.json() as Promise<SymbolDataResponse>
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

  // Monitoring endpoints
  getHealth: async () => {
    const response = await fetch(`${API_BASE_URL}/api/monitoring/health`)
    if (!response.ok) throw new Error('Failed to get health')
    return response.json() as Promise<SystemHealth>
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
    return response.json()
  },

  getTimeoutStats: async () => {
    const response = await fetch(`${API_BASE_URL}/api/monitoring/timeout/stats`)
    if (!response.ok) throw new Error('Failed to get timeout stats')
    return response.json()
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

export interface SymbolDataResponse {
  symbol: string
  data: {
    price?: number
    change?: number
    changePercent?: number
    volume?: number
    marketCap?: number
    [key: string]: any
  }
  timestamp: string
}

export interface BacktestRequest {
  symbol: string
  strategy: 'sma_crossover' | 'rsi_strategy' | 'buy_and_hold' | 'macd_strategy'
  start_date: string
  end_date: string
  initial_cash?: number
  commission?: number
  sma_short?: number
  sma_long?: number
  rsi_period?: number
  rsi_overbought?: number
  rsi_oversold?: number
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
  execution_time: number
}

export interface StrategiesResponse {
  strategies: Array<{
    name: string
    description: string
    parameters: Record<string, string>
  }>
}

export interface SystemHealth {
  status: string
  agents: Record<string, AgentHealth>
  uptime: number
  timestamp: string
}

export interface AgentHealth {
  health_score: number
  total_calls: number
  successful_calls: number
  failed_calls: number
  success_rate: number
  avg_latency: number
  p95_latency: number
  p99_latency: number
  last_error?: string
}

export interface CircuitBreakersResponse {
  [agentName: string]: {
    state: 'CLOSED' | 'OPEN' | 'HALF_OPEN'
    failure_count: number
    success_count: number
    last_failure_time?: string
    last_success_time?: string
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

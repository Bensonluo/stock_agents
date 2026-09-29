export interface AnalysisResult {
  thread_id: string
  query: string
  symbols: string[]
  decision?: {
    decisions?: Record<string, {
      symbol: string
      action: string
      confidence: number
      score: number
      component_scores?: {
        technical?: number
        fundamental?: number
        sentiment?: number
      }
      price_targets?: {
        current: number
        stop_loss?: number
        target?: number
      }
      position_size?: {
        percentage_of_portfolio?: number
        sizing_rationale?: string
      }
    }>
    portfolio_summary?: {
      total_symbols: number
      buy_recommendations: number
      sell_recommendations: number
      hold_recommendations: number
      avg_confidence: number
    }
    // IC 反馈边的 provenance：本次 run 的复合分混合来自静态 45/30/15
    // 还是测得的维度 IC（决策层每次 run 顶层发射，一块对整次 run）。
    dimension_weights?: {
      mode: 'static' | 'adaptive'
      reason?: string | null
      static_weights: Record<string, number>
      weights: Record<string, number>
      lambda?: number | null
      runs_weakest_dimension?: number | null
      runs_evaluated?: number | null
      horizon_bars?: number | null
      per_dimension?: Record<string, {
        qualified: boolean
        reason?: string
        runs?: number
        ic_mean?: number
        ic_positive_rate?: number
      }>
    }
  }
  report?: {
    sections?: Record<string, any>
  }
  technical_analysis?: any
  fundamental_analysis?: any
  sentiment_analysis?: any
  risk_assessment?: any
  agent_status: Record<string, string>
  execution_metadata?: {
    execution_time?: number
    had_errors?: boolean
  }
}

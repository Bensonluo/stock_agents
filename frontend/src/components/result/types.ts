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

// 期权隐含情绪标注 —— wire 上的 report.sections.risk_analysis.option_implied
// （ReAct 视图）或顶层 risk_assessment.option_implied（pipeline 视图）。
// 镜像 app/tools/data/option_signals.py::build_option_implied：仅当后端产出
// 时存在，降级 run 整键缺席（pipeline 形状键在值可为 null）。纯标注，不参与评分。
export interface OptionImpliedQvix {
  current: number
  as_of: string | null
  percentile_1y: number | null // 0-1 排名
  history_days: number
}

export interface OptionImpliedIv {
  status: string
  atm_iv_near: number | null // 比率：0.18 = 18%
  near_expiry: string | null
  atm_iv_next: number | null
  next_expiry: string | null
  term_structure: number | null // 近月 − 次月；负值 = 期限倒挂（近端恐慌）
  skew_25d: number | null // 认沽翼 − 认购翼（比率）
  n_contracts: number
  n_filtered: number
}

export interface OptionImpliedPcr {
  market_pcr: number | null
  by_underlying: Record<string, unknown>
}

export interface OptionImplied {
  status: 'ok' | 'insufficient_data'
  regime: string | null // '恐慌' | '自满' | '中性'，缺 QVIX 分位时为 null
  qvix: OptionImpliedQvix | null
  iv: OptionImpliedIv | null
  pcr: OptionImpliedPcr | null
  generated_at: string
}

// Three-tier interpretation functions for the measurement-chain panels.
// Extracted verbatim from the backtest forms and the monitoring page
// (iteration 126) so the statistical verdict semantics can be
// regression-tested — these decide when a result is labeled 显著、帮倒忙 or
// 与噪音不可区分, and a flipped tier mislabels statistical evidence.
// Colors follow the shared convention: emerald = confirmed edge, red =
// confirmed harm, amber = honestly inconclusive.

// 随机入场零假设的单侧 p 值判读(BacktestForm · NullBenchmarkCard)
export function nullBenchmarkVerdict(pValue: number): { text: string; cls: string } {
  // One-sided p: probability that random timing does at least as well.
  const isSignal = pValue <= 0.05
  const isAntiSignal = pValue >= 0.95
  return isSignal
    ? { text: '信号显著优于随机入场（p ≤ 0.05）', cls: 'text-emerald-600 dark:text-emerald-400' }
    : isAntiSignal
      ? { text: '显著差于随机入场——择时在帮倒忙', cls: 'text-red-500' }
      : { text: '与随机入场不可区分——收益更可能来自行情而非择时', cls: 'text-amber-600 dark:text-amber-400' }
}

// Deflated Sharpe 三档判读(WalkForwardForm · DeflatedSharpeCard)
export function deflatedSharpeVerdict(dsr: number): { text: string; cls: string } {
  const isSignificant = dsr >= 0.95
  const isDeflated = dsr <= 0.05
  return isSignificant
    ? {
        text: '折减选参偏差后 Sharpe 仍显著为正——选参结果可信',
        cls: 'text-emerald-600 dark:text-emerald-400',
      }
    : isDeflated
      ? { text: '选参优势在折减后消失——大概率是搜索幸存者', cls: 'text-red-500' }
      : { text: '尚不能把该 Sharpe 与选参噪音区分开', cls: 'text-amber-600 dark:text-amber-400' }
}

// 校准命中率 + Wilson 保守下界三档判读(CalibrationForm · horizonVerdict)
export function calibrationVerdict(
  hitRate: number | null,
  wilsonLower: number | null
): { text: string; cls: string } {
  if (hitRate === null) {
    return { text: '无成熟事件', cls: 'text-amber-600 dark:text-amber-400' }
  }
  if (wilsonLower !== null && wilsonLower > 0.5) {
    return {
      text: '保守下界仍在 50% 之上——命中率经得起样本量折减',
      cls: 'text-emerald-600 dark:text-emerald-400',
    }
  }
  if (hitRate < 0.5) {
    return { text: '历史命中率不足一半——入场信号更常错误', cls: 'text-red-500' }
  }
  return {
    text: '命中率过半但保守下界未过半——样本量还不足以确证优势',
    cls: 'text-amber-600 dark:text-amber-400',
  }
}

// 数据源健康三档(monitoring 页 · DataSourceHealthPanel/AgentHealthPanel)
export type ProviderTone = 'healthy' | 'degraded' | 'down'

export function providerTone(stats: {
  ok: number
  fallback: number
  fail: number
}): ProviderTone {
  if (stats.fail === 0) return 'healthy'
  if (stats.ok + stats.fallback === 0) return 'down'
  return 'degraded'
}

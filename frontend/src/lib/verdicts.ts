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

// ── IC t-stat 判读(SignalQualityCard,iteration 127 提取)───────────────
// Daily runs share most of the forward window, so the i.i.d. t overstates
// significance exactly there — wherever the Newey-West t is available it
// is the honest basis for the verdict (same preference as the aggregate
// view and the regime bins).

// NW 优先的判读 t:Newey-West 为数字就用它,缺席回退原始 t,都缺 → null。
export function preferredTStat(
  tNw: number | null | undefined,
  tRaw: number | null | undefined
): number | null {
  if (typeof tNw === 'number') return tNw
  if (typeof tRaw === 'number') return tRaw
  return null
}

export type TStatTier = 'signal' | 'anti' | 'inconclusive'

// |t| ≥ 2 三档;缺席(样本短/离散度不可估)≡ 无法判读,绝不当作 t=0。
export function tStatTier(t: number | null | undefined): TStatTier {
  if (typeof t !== 'number') return 'inconclusive'
  if (t >= 2) return 'signal'
  if (t <= -2) return 'anti'
  return 'inconclusive'
}

export const T_STAT_CLS: Record<TStatTier, string> = {
  signal: 'text-emerald-600 dark:text-emerald-400',
  anti: 'text-red-500',
  inconclusive: '',
}

// 聚合 IC 头条判读(SignalQualityCard verdict 行)
export function tStatVerdict(t: number | null | undefined): { text: string; cls: string } {
  const tier = tStatTier(t)
  if (tier === 'signal') {
    return {
      text: '决策分数的相对排序显著预测了前向收益（t ≥ 2）',
      cls: T_STAT_CLS.signal,
    }
  }
  if (tier === 'anti') {
    return {
      text: '排序显著反向——分数高的标的前向反而跑输',
      cls: T_STAT_CLS.anti,
    }
  }
  return {
    text: '尚无法与随机排序区分——需要更多已成熟的多标的 run',
    cls: 'text-amber-600 dark:text-amber-400',
  }
}

// ── 校准 gap 三档(SignalQualityCard,iteration 127 提取)───────────────

export type CalibrationGapTier = 'overconfident' | 'conservative' | 'aligned'

// 平均声称置信度 − 实证正确率:≥ +5pp 过度自信 / ≤ −5pp 保守 / 其间对齐。
export function calibrationGapTier(gap: number): CalibrationGapTier {
  if (gap >= 0.05) return 'overconfident'
  if (gap <= -0.05) return 'conservative'
  return 'aligned'
}

export const CALIBRATION_GAP_CLS: Record<CalibrationGapTier, string> = {
  overconfident: 'text-amber-600 dark:text-amber-400',
  conservative: 'text-blue-500',
  aligned: 'text-emerald-600 dark:text-emerald-400',
}

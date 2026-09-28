'use client'

import { useCallback, useEffect, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Loader2, Target } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  API,
  type ConfidenceCalibrationResponse,
  type DecisionICResponse,
  type ICDecayResponse,
  type RegimeBinSummary,
  type RegimeConditionalICResponse,
  type TopKPortfolioResponse,
} from '@/lib/utils'

const HORIZONS = [
  { value: '10', label: '10 交易日' },
  { value: '20', label: '20 交易日' },
  { value: '60', label: '60 交易日' },
]

const DIMENSION_LABELS: Record<string, string> = {
  technical: '技术面',
  fundamental: '基本面',
  sentiment: '情绪面',
}

const REGIME_BIN_LABELS: Record<string, string> = {
  bull: '牛市',
  bear: '熊市',
  neutral: '震荡',
  unknown: '未记录',
}

function fmt(value: number | null | undefined, digits = 3): string {
  return typeof value === 'number' ? value.toFixed(digits) : '—'
}

export function SignalQualityCard() {
  const [horizon, setHorizon] = useState('20')
  const [ic, setIc] = useState<DecisionICResponse | null>(null)
  const [decay, setDecay] = useState<ICDecayResponse | null>(null)
  const [calib, setCalib] = useState<ConfidenceCalibrationResponse | null>(null)
  const [regimeIc, setRegimeIc] = useState<RegimeConditionalICResponse | null>(null)
  const [topk, setTopk] = useState<TopKPortfolioResponse | null>(null)
  const [topK, setTopK] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (h: string) => {
    setLoading(true)
    setError(null)
    // Calibration shares the horizon but not the fate of the IC fetch — a
    // single directional claim calibrates where a cross-section cannot.
    void API.getConfidenceCalibration(parseInt(h))
      .then(setCalib)
      .catch(() => setCalib(null))
    // Regime bins share the horizon too, and stay quiet on fetch failure —
    // the aggregate IC view renders fine without them.
    void API.getRegimeConditionalIC(parseInt(h))
      .then(setRegimeIc)
      .catch(() => setRegimeIc(null))
    try {
      setIc(await API.getDecisionIC(parseInt(h)))
    } catch {
      setError('信号质量评估暂不可用')
      setIc(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load(horizon)
  }, [horizon, load])

  // The decay curve is horizon-independent — fetch it once on mount.
  useEffect(() => {
    API.getDecisionICDecay()
      .then(setDecay)
      .catch(() => setDecay(null))
  }, [])

  // The money-terms view shares the horizon and adds its own knob: how many
  // top-scored names the replayed portfolio holds. Quiet on failure — the
  // ranking views render fine without it.
  useEffect(() => {
    void API.getTopKPortfolio(parseInt(horizon), topK)
      .then(setTopk)
      .catch(() => setTopk(null))
  }, [horizon, topK])

  // Prefer the Newey-West t for the verdict: daily runs share most of the
  // forward window, and the i.i.d. t overstates significance exactly there.
  const tForVerdict = typeof ic?.t_stat_nw === 'number' ? ic.t_stat_nw : ic?.t_stat
  const isSignal = typeof tForVerdict === 'number' && tForVerdict >= 2
  const isAntiSignal = typeof tForVerdict === 'number' && tForVerdict <= -2
  const dimEntries = Object.entries(ic?.dimensions ?? {}).filter(
    (entry): entry is [string, NonNullable<typeof entry[1]>] => entry[1] !== null
  )
  const decayPoints = (decay?.horizons ?? []).filter(
    (p) => p.status === 'ok' || p.runs_pending_maturity > 0
  )
  // Bins with zero runs render nothing — an empty regime has no story.
  const regimeEntries = Object.entries(regimeIc?.regimes ?? {}).filter(
    (entry): entry is [string, RegimeBinSummary] => entry[1].runs > 0
  )
  const calibGap =
    typeof calib?.avg_confidence === 'number' && typeof calib?.base_rate === 'number'
      ? calib.avg_confidence - calib.base_rate
      : null
  const calibVerdict =
    calibGap === null
      ? null
      : calibGap >= 0.05
        ? {
            text: `系统性过度自信——平均声称 ${(calib!.avg_confidence! * 100).toFixed(0)}%，实证只对 ${(calib!.base_rate! * 100).toFixed(0)}%`,
            cls: 'text-amber-600 dark:text-amber-400',
          }
        : calibGap <= -0.05
          ? {
              text: `系统性保守——实证正确率高出声称 ${(Math.abs(calibGap) * 100).toFixed(0)} 个百分点`,
              cls: 'text-blue-500',
            }
          : { text: '置信度与实证正确率基本对齐（偏差 <5 个百分点）', cls: 'text-emerald-600 dark:text-emerald-400' }
  const reliabilityBins = calib?.reliability ?? []
  const verdict = isSignal
    ? { text: '决策分数的相对排序显著预测了前向收益（t ≥ 2）', cls: 'text-emerald-600 dark:text-emerald-400' }
    : isAntiSignal
      ? { text: '排序显著反向——分数高的标的前向反而跑输', cls: 'text-red-500' }
      : { text: '尚无法与随机排序区分——需要更多已成熟的多标的 run', cls: 'text-amber-600 dark:text-amber-400' }

  return (
    <Card className="shadow-lg shadow-slate-900/5">
      <CardHeader>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Target className="h-5 w-5" />
              决策信号质量 · 秩 IC 与置信度校准
            </CardTitle>
            <CardDescription>
              复合分 vs 前向收益的 Spearman 秩 IC（逐 run 聚合为 ICIR）；置信度 vs 实证正确率的 Brier
              校准
            </CardDescription>
          </div>
          <Select value={horizon} onValueChange={setHorizon} disabled={loading}>
            <SelectTrigger className="w-[130px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {HORIZONS.map((h) => (
                <SelectItem key={h.value} value={h.value}>
                  {h.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading && !ic ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-blue-500" />
          </div>
        ) : error ? (
          <p className="text-sm text-muted-foreground py-4 text-center">{error}</p>
        ) : ic && ic.status === 'ok' ? (
          <>
            <div className={`text-sm font-semibold ${verdict.cls}`}>{verdict.text}</div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="p-3 bg-muted/50 rounded-lg">
                <div className="text-xs text-muted-foreground">IC 均值</div>
                <div className="text-lg font-bold">{fmt(ic.ic_mean)}</div>
              </div>
              <div className="p-3 bg-muted/50 rounded-lg">
                <div className="text-xs text-muted-foreground">ICIR</div>
                <div className="text-lg font-bold">{fmt(ic.icir)}</div>
              </div>
              <div className="p-3 bg-muted/50 rounded-lg">
                <div className="text-xs text-muted-foreground">
                  t 统计量{typeof ic.t_stat_nw === 'number' ? ' · NW' : ''}
                </div>
                <div className="text-lg font-bold">
                  {fmt(typeof ic.t_stat_nw === 'number' ? ic.t_stat_nw : ic.t_stat, 2)}
                </div>
              </div>
              <div className="p-3 bg-muted/50 rounded-lg">
                <div className="text-xs text-muted-foreground">正 IC run 占比</div>
                <div className="text-lg font-bold">
                  {typeof ic.ic_positive_rate === 'number'
                    ? `${(ic.ic_positive_rate * 100).toFixed(0)}%`
                    : '—'}
                </div>
              </div>
            </div>
            <div className="text-xs text-muted-foreground">
              {ic.runs_evaluated} 个 run 已评估 · {ic.runs_pending_maturity} 个待窗口成熟 ·{' '}
              {ic.runs_skipped} 个跳过 · {ic.horizon_bars} 交易日窗口
              {ic.icir === null && ic.runs_evaluated === 1 ? '（单 run 有均值，ICIR 待积累）' : ''}
            </div>
            {ic.per_run.length > 0 && (
              <div className="space-y-1">
                <div className="text-xs font-medium text-muted-foreground">近期 run 的 IC</div>
                {ic.per_run.slice(-6).reverse().map((run) => (
                  <div
                    key={run.thread_id}
                    className="flex items-center justify-between text-xs py-1 border-b border-border/40 last:border-0"
                  >
                    <span className="text-muted-foreground">
                      {run.date} · {run.symbols} 标的
                      {run.regime_trend
                        ? ` · ${REGIME_BIN_LABELS[run.regime_trend] ?? run.regime_trend}`
                        : ''}
                    </span>
                    <span
                      className={
                        run.ic > 0
                          ? 'font-semibold text-emerald-600 dark:text-emerald-400'
                          : run.ic < 0
                            ? 'font-semibold text-red-500'
                            : 'font-semibold'
                      }
                    >
                      {run.ic >= 0 ? '+' : ''}
                      {run.ic.toFixed(3)}
                    </span>
                  </div>
                ))}
              </div>
            )}
            {dimEntries.length > 0 && (
              <div className="space-y-1">
                <div className="text-xs font-medium text-muted-foreground">
                  维度归因 · 各维度对同一前向收益的秩 IC
                </div>
                {dimEntries.map(([dimension, summary]) => (
                  <div
                    key={dimension}
                    className="flex items-center justify-between text-xs py-1 border-b border-border/40 last:border-0"
                  >
                    <span className="text-muted-foreground">
                      {DIMENSION_LABELS[dimension] ?? dimension} · {summary.runs} run
                    </span>
                    <span className="flex items-center gap-3">
                      <span className="text-muted-foreground">IC {fmt(summary.ic_mean)}</span>
                      <span
                        className={
                          typeof summary.t_stat === 'number' && summary.t_stat >= 2
                            ? 'font-semibold text-emerald-600 dark:text-emerald-400'
                            : typeof summary.t_stat === 'number' && summary.t_stat <= -2
                              ? 'font-semibold text-red-500'
                              : 'font-semibold'
                        }
                      >
                        t {fmt(summary.t_stat, 2)}
                      </span>
                      {typeof summary.t_stat_nw === 'number' && (
                        <span className="text-muted-foreground">
                          t·NW {fmt(summary.t_stat_nw, 2)}
                        </span>
                      )}
                    </span>
                  </div>
                ))}
                <p className="text-[11px] text-muted-foreground/70 pt-1">
                  复合分权重（基本面 45 / 技术面 30 / 情绪面 15）的实证对账——哪个维度真的在排序收益。
                </p>
              </div>
            )}
            {decayPoints.length > 0 && (
              <div className="space-y-1">
                <div className="text-xs font-medium text-muted-foreground">
                  IC 衰减 · 点击切换主窗口
                </div>
                <div className="flex flex-wrap gap-2">
                  {decayPoints.map((point) => {
                    const active = String(point.horizon_bars) === horizon
                    const cls =
                      typeof point.t_stat === 'number' && point.t_stat >= 2
                        ? 'text-emerald-600 dark:text-emerald-400'
                        : typeof point.t_stat === 'number' && point.t_stat <= -2
                          ? 'text-red-500'
                          : ''
                    return (
                      <Button
                        key={point.horizon_bars}
                        variant={active ? 'default' : 'outline'}
                        size="sm"
                        className="h-7 px-2 text-xs"
                        onClick={() => setHorizon(String(point.horizon_bars))}
                      >
                        {point.horizon_bars}d
                        <span className={active ? '' : cls}>
                          {point.status === 'ok' && typeof point.ic_mean === 'number'
                            ? `${point.ic_mean >= 0 ? '+' : ''}${point.ic_mean.toFixed(3)}`
                            : '—'}
                        </span>
                      </Button>
                    )
                  })}
                </div>
                <p className="text-[11px] text-muted-foreground/70 pt-1">
                  排序能力随持有期拉长的衰减——IC 在哪个窗口最大，信号的天然持有期就在哪。
                </p>
              </div>
            )}
          </>
        ) : ic ? (
          <div className="space-y-2 py-2">
            <p className="text-sm text-amber-600 dark:text-amber-400">
              历史尚不足以计算截面 IC
            </p>
            <p className="text-xs text-muted-foreground">
              截面 IC 需要每 run ≥3 个有复合分的标的、且前向窗口已成熟。当前 {ic.records_examined}{' '}
              条记录：{ic.runs_evaluated} 条可评估、{ic.runs_pending_maturity} 条待成熟、
              {ic.runs_skipped} 条跳过（单标的或数据缺失的 run 不参与截面排序）。
              多标的分析积累后此处自动点亮。
            </p>
          </div>
        ) : null}
        {calib && calib.status === 'ok' && typeof calib.brier_score === 'number' ? (
          <div className="space-y-3 border-t pt-3">
            <div className="text-xs font-medium text-muted-foreground">
              置信度校准 · Brier / 可靠性
            </div>
            {calibVerdict && <div className={`text-sm font-semibold ${calibVerdict.cls}`}>{calibVerdict.text}</div>}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="p-3 bg-muted/50 rounded-lg">
                <div className="text-xs text-muted-foreground">Brier 分</div>
                <div className="text-lg font-bold">{fmt(calib.brier_score)}</div>
              </div>
              <div className="p-3 bg-muted/50 rounded-lg">
                <div className="text-xs text-muted-foreground">Brier skill</div>
                <div
                  className={`text-lg font-bold ${
                    typeof calib.brier_skill_score === 'number'
                      ? calib.brier_skill_score < 0
                        ? 'text-red-500'
                        : calib.brier_skill_score > 0
                          ? 'text-emerald-600 dark:text-emerald-400'
                          : ''
                      : ''
                  }`}
                >
                  {fmt(calib.brier_skill_score)}
                </div>
              </div>
              <div className="p-3 bg-muted/50 rounded-lg">
                <div className="text-xs text-muted-foreground">平均声称置信度</div>
                <div className="text-lg font-bold">
                  {typeof calib.avg_confidence === 'number'
                    ? `${(calib.avg_confidence * 100).toFixed(0)}%`
                    : '—'}
                </div>
              </div>
              <div className="p-3 bg-muted/50 rounded-lg">
                <div className="text-xs text-muted-foreground">实证正确率</div>
                <div className="text-lg font-bold">
                  {typeof calib.base_rate === 'number'
                    ? `${(calib.base_rate * 100).toFixed(0)}%`
                    : '—'}
                </div>
              </div>
            </div>
            {reliabilityBins.length > 0 && (
              <div className="space-y-1">
                <div className="text-xs font-medium text-muted-foreground">
                  可靠性分桶 · 声称 vs 实证
                </div>
                {reliabilityBins.map((bin) => {
                  const gap = bin.avg_confidence - bin.empirical_rate
                  return (
                    <div
                      key={`${bin.bin_low}-${bin.bin_high}`}
                      className="flex items-center justify-between text-xs py-1 border-b border-border/40 last:border-0"
                    >
                      <span className="text-muted-foreground">
                        [{bin.bin_low.toFixed(1)}–{bin.bin_high.toFixed(1)}) · n={bin.n}
                      </span>
                      <span className="flex items-center gap-3">
                        <span>声称 {(bin.avg_confidence * 100).toFixed(0)}%</span>
                        <span>实证 {(bin.empirical_rate * 100).toFixed(0)}%</span>
                        <span
                          className={
                            gap >= 0.05
                              ? 'font-semibold text-amber-600 dark:text-amber-400'
                              : gap <= -0.05
                                ? 'font-semibold text-blue-500'
                                : 'font-semibold text-emerald-600 dark:text-emerald-400'
                          }
                        >
                          {gap >= 0 ? '+' : ''}
                          {(gap * 100).toFixed(0)}pp
                        </span>
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
            <div className="text-xs text-muted-foreground">
              {calib.predictions} 条 buy/sell 方向主张已对账 · {calib.runs_pending_maturity} run
              待窗口成熟
              {typeof calib.runs_duplicate === 'number' && calib.runs_duplicate > 0
                ? ` · ${calib.runs_duplicate} 条重复已剔除`
                : ''}{' '}
              · 平盘对双向均判错 · hold 不参与
            </div>
            <p className="text-[11px] text-muted-foreground/70">{calib.caveat}</p>
          </div>
        ) : calib ? (
          <div className="space-y-2 border-t pt-3">
            <p className="text-sm text-amber-600 dark:text-amber-400">
              历史尚不足以校准置信度
            </p>
            <p className="text-xs text-muted-foreground">
              校准只需已成熟的 buy/sell 方向主张（hold 无方向主张、不参与）。当前{' '}
              {calib.records_examined} 条记录：{calib.runs_pending_maturity} 条待前向窗口成熟、
              {calib.runs_skipped} 条无可校准主张。方向性主张积累后此处自动点亮。
            </p>
          </div>
        ) : null}
        {regimeEntries.length > 0 && (
          <div className="space-y-1 border-t pt-3">
            <div className="text-xs font-medium text-muted-foreground">
              市场状态分桶 · 推荐排序在哪种市场里更可信
            </div>
            <div className="flex flex-wrap gap-2">
              {regimeEntries.map(([name, bin]) => {
                // Same NW preference as the aggregate view.
                const tNw = typeof bin.t_stat_nw === 'number' ? bin.t_stat_nw : null
                const t =
                  tNw !== null
                    ? tNw
                    : typeof bin.t_stat === 'number'
                      ? bin.t_stat
                      : null
                const cls =
                  t !== null && t >= 2
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : t !== null && t <= -2
                      ? 'text-red-500'
                      : ''
                return (
                  <div key={name} className="px-2 py-1 rounded-md bg-muted/50 text-xs">
                    <span className="text-muted-foreground">
                      {REGIME_BIN_LABELS[name] ?? name} · {bin.runs} run
                    </span>{' '}
                    {typeof bin.ic_mean === 'number' ? (
                      <span className={bin.status === 'ok' ? `font-semibold ${cls}` : ''}>
                        {bin.ic_mean >= 0 ? '+' : ''}
                        {bin.ic_mean.toFixed(3)}
                        {bin.status === 'ok' && t !== null ? (
                          <span className="text-muted-foreground"> · t {t.toFixed(2)}</span>
                        ) : (
                          <span className="text-muted-foreground"> · 样本不足</span>
                        )}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">样本不足</span>
                    )}
                  </div>
                )
              })}
            </div>
            <div className="text-xs text-muted-foreground">
              同一份重放按 run 当时基准分类的市场状态分桶 · regime 上线前的历史与基准降级跑单列「未记录」
            </div>
          </div>
        )}
        {topk && topk.status === 'ok' && typeof topk.excess_mean === 'number' ? (
          <div className="space-y-2 border-t pt-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-xs font-medium text-muted-foreground">
                照做收益 · 前 {topk.top_k} 名等权 vs 全截面等权（{topk.horizon_bars} 交易日）
              </div>
              <div className="flex gap-1">
                {[1, 2, 3, 5].map((k) => (
                  <Button
                    key={k}
                    variant={topk.top_k === k ? 'default' : 'outline'}
                    size="sm"
                    className="h-6 px-2 text-xs"
                    onClick={() => setTopK(k)}
                  >
                    前{k}
                  </Button>
                ))}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
              <span
                className={
                  topk.excess_mean > 0
                    ? 'font-semibold text-emerald-600 dark:text-emerald-400'
                    : topk.excess_mean < 0
                      ? 'font-semibold text-red-500'
                      : 'font-semibold'
                }
              >
                平均超额 {(topk.excess_mean * 100).toFixed(2)}%
              </span>
              <span className="text-muted-foreground">
                跑赢基准 run 占比{' '}
                {typeof topk.hit_rate === 'number' ? `${(topk.hit_rate * 100).toFixed(0)}%` : '—'}
              </span>
              {typeof topk.excess_std === 'number' && (
                <span className="text-muted-foreground">
                  超额 σ {(topk.excess_std * 100).toFixed(2)}%
                </span>
              )}
              {typeof topk.excess_t_stat === 'number' && (
                <span className="text-muted-foreground">
                  t{' '}
                  <span
                    className={
                      topk.excess_t_stat >= 2
                        ? 'text-emerald-600 dark:text-emerald-400'
                        : topk.excess_t_stat <= -2
                          ? 'text-red-500'
                          : ''
                    }
                  >
                    {topk.excess_t_stat.toFixed(2)}
                  </span>
                </span>
              )}
              {typeof topk.excess_t_stat_nw === 'number' && (
                <span className="text-muted-foreground">
                  t·NW{' '}
                  <span
                    className={
                      topk.excess_t_stat_nw >= 2
                        ? 'text-emerald-600 dark:text-emerald-400'
                        : topk.excess_t_stat_nw <= -2
                          ? 'text-red-500'
                          : ''
                    }
                  >
                    {topk.excess_t_stat_nw.toFixed(2)}
                  </span>
                </span>
              )}
            </div>
            {topk.per_run.slice(-6).reverse().map((run) => (
              <div
                key={run.thread_id}
                className="flex items-center justify-between text-xs py-1 border-b border-border/40 last:border-0"
              >
                <span className="text-muted-foreground">
                  {run.date} · {run.symbols} 标的
                  {run.regime_trend
                    ? ` · ${REGIME_BIN_LABELS[run.regime_trend] ?? run.regime_trend}`
                    : ''}
                </span>
                <span
                  className={
                    run.excess > 0
                      ? 'font-semibold text-emerald-600 dark:text-emerald-400'
                      : run.excess < 0
                        ? 'font-semibold text-red-500'
                        : 'font-semibold'
                  }
                >
                  照做 {(run.top_return * 100).toFixed(2)}% vs 基准{' '}
                  {(run.baseline_return * 100).toFixed(2)}% → {run.excess >= 0 ? '+' : ''}
                  {(run.excess * 100).toFixed(2)}pp
                </span>
              </div>
            ))}
            <div className="text-xs text-muted-foreground">
              {topk.runs_evaluated} 个 run 已评估
              {topk.runs_pending_maturity > 0
                ? ` · ${topk.runs_pending_maturity} 个待窗口成熟`
                : ''}
              {topk.runs_narrow > 0 ? ` · ${topk.runs_narrow} 个截面过窄（不足 k+1 标的）` : ''}
              {topk.runs_duplicate > 0 ? ` · ${topk.runs_duplicate} 条重复已剔除` : ''}
            </div>
            <p className="text-[11px] text-muted-foreground/70">{topk.caveat}</p>
          </div>
        ) : topk ? (
          <div className="space-y-1 border-t pt-3">
            <p className="text-sm text-amber-600 dark:text-amber-400">历史尚不足以核算照做收益</p>
            <p className="text-xs text-muted-foreground">
              需要 ≥{topk.top_k + 1} 个有分标的、前向窗口已成熟的 run 累计至少 2 个。当前{' '}
              {topk.records_examined} 条记录：{topk.runs_evaluated} 条已评估、
              {topk.runs_pending_maturity} 条待成熟、{topk.runs_narrow} 条截面过窄。多标的 run
              积累后此处自动点亮。
            </p>
          </div>
        ) : null}
        {ic && (
          <p className="text-[11px] text-muted-foreground/70 border-t pt-2">{ic.caveat}</p>
        )}
      </CardContent>
    </Card>
  )
}

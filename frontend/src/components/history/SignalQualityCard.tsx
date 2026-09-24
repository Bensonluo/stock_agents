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

function fmt(value: number | null | undefined, digits = 3): string {
  return typeof value === 'number' ? value.toFixed(digits) : '—'
}

export function SignalQualityCard() {
  const [horizon, setHorizon] = useState('20')
  const [ic, setIc] = useState<DecisionICResponse | null>(null)
  const [decay, setDecay] = useState<ICDecayResponse | null>(null)
  const [calib, setCalib] = useState<ConfidenceCalibrationResponse | null>(null)
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

  const isSignal = typeof ic?.t_stat === 'number' && ic.t_stat >= 2
  const isAntiSignal = typeof ic?.t_stat === 'number' && ic.t_stat <= -2
  const dimEntries = Object.entries(ic?.dimensions ?? {}).filter(
    (entry): entry is [string, NonNullable<typeof entry[1]>] => entry[1] !== null
  )
  const decayPoints = (decay?.horizons ?? []).filter(
    (p) => p.status === 'ok' || p.runs_pending_maturity > 0
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
                <div className="text-xs text-muted-foreground">t 统计量</div>
                <div className="text-lg font-bold">{fmt(ic.t_stat, 2)}</div>
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
              待窗口成熟 · 平盘对双向均判错 · hold 不参与
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
        {ic && (
          <p className="text-[11px] text-muted-foreground/70 border-t pt-2">{ic.caveat}</p>
        )}
      </CardContent>
    </Card>
  )
}

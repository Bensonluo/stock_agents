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
import { API, type DecisionICResponse, type ICDecayResponse } from '@/lib/utils'

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
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (h: string) => {
    setLoading(true)
    setError(null)
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
              决策信号质量 · 秩 IC
            </CardTitle>
            <CardDescription>
              历史推荐的每 symbol 复合分 vs 实现的前向收益（Spearman 秩相关，逐 run IC 聚合为 ICIR）
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
        {ic && (
          <p className="text-[11px] text-muted-foreground/70 border-t pt-2">{ic.caveat}</p>
        )}
      </CardContent>
    </Card>
  )
}

'use client'

import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Loader2, Target } from 'lucide-react'
import {
  API,
  type CalibrateRequest,
  type CalibrateResponse,
  type CalibrationHorizon,
  type StrategiesResponse,
} from '@/lib/utils'

// Same filter as the walk-forward tab: buy-and-hold has no entry signal to
// calibrate (its single "entry" is bar zero — time itself, not a signal).
const TUNABLE_STRATEGIES = new Set(['sma_crossover', 'rsi_strategy', 'macd_strategy', 'technical_score'])

export function CalibrationForm() {
  const [strategies, setStrategies] = useState<StrategiesResponse | null>(null)
  const [symbol, setSymbol] = useState('AAPL')
  const [strategy, setStrategy] = useState('sma_crossover')
  const [startDate, setStartDate] = useState('2021-01-01')
  const [endDate, setEndDate] = useState('2024-01-01')
  const [horizons, setHorizons] = useState('20, 60')
  const [benchmark, setBenchmark] = useState('')
  const [smaShort, setSmaShort] = useState('20')
  const [smaLong, setSmaLong] = useState('50')
  const [rsiPeriod, setRsiPeriod] = useState('14')
  const [rsiOverbought, setRsiOverbought] = useState('70')
  const [rsiOversold, setRsiOversold] = useState('30')
  const [fastPeriod, setFastPeriod] = useState('12')
  const [slowPeriod, setSlowPeriod] = useState('26')
  const [signalPeriod, setSignalPeriod] = useState('9')
  const [scoreThreshold, setScoreThreshold] = useState('10')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<CalibrateResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    API.getStrategies().then(setStrategies).catch(console.error)
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const parsedHorizons = horizons
        .split(',')
        .map((s) => s.trim())
        .filter((s) => s.length > 0)
        .map(Number)
      if (parsedHorizons.length === 0 || parsedHorizons.some((v) => !Number.isFinite(v) || v < 1)) {
        throw new Error('持有视野列表无效——请输入逗号分隔的正整数（如 20, 60，单位为交易日）')
      }

      const rawParams: Record<string, string> =
        strategy === 'sma_crossover'
          ? { sma_short: smaShort, sma_long: smaLong }
          : strategy === 'rsi_strategy'
            ? { rsi_period: rsiPeriod, rsi_overbought: rsiOverbought, rsi_oversold: rsiOversold }
            : strategy === 'technical_score'
              ? { score_threshold: scoreThreshold }
              : { fast_period: fastPeriod, slow_period: slowPeriod, signal_period: signalPeriod }

      const strategy_params: Record<string, number> = {}
      for (const [name, raw] of Object.entries(rawParams)) {
        const value = Number(raw)
        if (!Number.isFinite(value)) {
          throw new Error(`参数 ${name} 无效——请输入数字`)
        }
        strategy_params[name] = value
      }

      const trimmedBenchmark = benchmark.trim().toUpperCase()
      const request: CalibrateRequest = {
        symbol: symbol.toUpperCase(),
        strategy: strategy as CalibrateRequest['strategy'],
        start_date: startDate,
        end_date: endDate,
        horizons: [...new Set(parsedHorizons)],
        strategy_params,
        ...(trimmedBenchmark ? { benchmark_symbol: trimmedBenchmark } : {}),
      }

      setResult(await API.calibrateSignals(request))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Calibration failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Target className="h-5 w-5" />
            信号校准
          </CardTitle>
          <CardDescription>
            入场信号的事后命中率 · Wilson 保守下界按样本量折减 · 分年分解暴露失效年份
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="cal-symbol">Stock Symbol</Label>
                <Input
                  id="cal-symbol"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                  disabled={loading}
                  placeholder="AAPL / 600000"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="cal-strategy">Strategy</Label>
                <Select value={strategy} onValueChange={setStrategy} disabled={loading}>
                  <SelectTrigger id="cal-strategy">
                    <SelectValue placeholder="Select strategy" />
                  </SelectTrigger>
                  <SelectContent>
                    {strategies?.strategies
                      .filter((s) => TUNABLE_STRATEGIES.has(s.name))
                      .map((s) => (
                        <SelectItem key={s.name} value={s.name}>
                          {s.description}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="cal-start">Start Date</Label>
                <Input
                  id="cal-start"
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  disabled={loading}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="cal-end">End Date</Label>
                <Input
                  id="cal-end"
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  disabled={loading}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="cal-horizons">持有视野（交易日，逗号分隔）</Label>
                <Input
                  id="cal-horizons"
                  value={horizons}
                  onChange={(e) => setHorizons(e.target.value)}
                  disabled={loading}
                  placeholder="20, 60"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="cal-benchmark">基准（可选）</Label>
                <Input
                  id="cal-benchmark"
                  value={benchmark}
                  onChange={(e) => setBenchmark(e.target.value.toUpperCase())}
                  disabled={loading}
                  placeholder="如 SPY——命中=跑赢基准，留空=绝对收益为正"
                />
              </div>

              {strategy === 'sma_crossover' && (
                <>
                  <div className="space-y-2">
                    <Label htmlFor="cal-sma-short">Short Period</Label>
                    <Input
                      id="cal-sma-short"
                      type="number"
                      value={smaShort}
                      onChange={(e) => setSmaShort(e.target.value)}
                      disabled={loading}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="cal-sma-long">Long Period</Label>
                    <Input
                      id="cal-sma-long"
                      type="number"
                      value={smaLong}
                      onChange={(e) => setSmaLong(e.target.value)}
                      disabled={loading}
                    />
                  </div>
                </>
              )}

              {strategy === 'rsi_strategy' && (
                <>
                  <div className="space-y-2">
                    <Label htmlFor="cal-rsi-period">RSI Period</Label>
                    <Input
                      id="cal-rsi-period"
                      type="number"
                      value={rsiPeriod}
                      onChange={(e) => setRsiPeriod(e.target.value)}
                      disabled={loading}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="cal-rsi-ob">Overbought</Label>
                    <Input
                      id="cal-rsi-ob"
                      type="number"
                      value={rsiOverbought}
                      onChange={(e) => setRsiOverbought(e.target.value)}
                      disabled={loading}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="cal-rsi-os">Oversold</Label>
                    <Input
                      id="cal-rsi-os"
                      type="number"
                      value={rsiOversold}
                      onChange={(e) => setRsiOversold(e.target.value)}
                      disabled={loading}
                    />
                  </div>
                </>
              )}

              {strategy === 'macd_strategy' && (
                <>
                  <div className="space-y-2">
                    <Label htmlFor="cal-fast">Fast EMA</Label>
                    <Input
                      id="cal-fast"
                      type="number"
                      value={fastPeriod}
                      onChange={(e) => setFastPeriod(e.target.value)}
                      disabled={loading}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="cal-slow">Slow EMA</Label>
                    <Input
                      id="cal-slow"
                      type="number"
                      value={slowPeriod}
                      onChange={(e) => setSlowPeriod(e.target.value)}
                      disabled={loading}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="cal-signal">Signal EMA</Label>
                    <Input
                      id="cal-signal"
                      type="number"
                      value={signalPeriod}
                      onChange={(e) => setSignalPeriod(e.target.value)}
                      disabled={loading}
                    />
                  </div>
                </>
              )}

              {strategy === 'technical_score' && (
                <div className="space-y-2">
                  <Label htmlFor="cal-score-threshold">Score Threshold</Label>
                  <Input
                    id="cal-score-threshold"
                    type="number"
                    value={scoreThreshold}
                    onChange={(e) => setScoreThreshold(e.target.value)}
                    disabled={loading}
                  />
                  <p className="text-xs text-muted-foreground">
                    决策层技术面分的买入阈值（−100..100）；10 = 线上管线的 moderate_buy 档线
                  </p>
                </div>
              )}
            </div>

            {error && (
              <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-md">
                {error}
              </div>
            )}

            <Button type="submit" disabled={loading} className="w-full">
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Calibrating...
                </>
              ) : (
                <>
                  <Target className="mr-2 h-4 w-4" />
                  Run Calibration
                </>
              )}
            </Button>
          </form>
        </CardContent>
      </Card>

      {result && <CalibrationResult result={result} />}
    </div>
  )
}

interface CalibrationResultProps {
  result: CalibrateResponse
}

function CalibrationResult({ result }: CalibrationResultProps) {
  const horizonKeys = Object.keys(result.by_horizon)
    .map(Number)
    .sort((a, b) => a - b)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>校准结果</span>
          <span className="text-sm font-normal text-muted-foreground">
            {result.entries_total} 次入场 · {formatParams(result.params)}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {horizonKeys.map((h) => (
          <HorizonBlock key={h} horizon={h} block={result.by_horizon[String(h)]} />
        ))}
        <div className="text-xs text-muted-foreground pt-2 border-t">
          命中 = 前向 close-to-close 收益跑赢基准（未填基准时 = 绝对收益为正）；Wilson 下界按
          95% 置信把命中率往保守侧折减——样本越小折得越狠。
        </div>
      </CardContent>
    </Card>
  )
}

function HorizonBlock({ horizon, block }: { horizon: number; block: CalibrationHorizon }) {
  const verdict = horizonVerdict(block)
  const years = Object.keys(block.by_year).sort()

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <div className="text-sm font-medium">持有 {horizon} 个交易日</div>
        <div className={`text-sm font-semibold ${verdict.cls}`}>{verdict.text}</div>
      </div>

      {block.hit_rate === null ? (
        <div className="text-sm text-muted-foreground">
          该视野内没有足够成熟的前向事件——如实显示而非按 0 计
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="p-3 bg-muted/50 rounded-lg">
              <div className="text-xs text-muted-foreground">命中率</div>
              <div className="text-lg font-bold">{(block.hit_rate * 100).toFixed(1)}%</div>
            </div>
            <div className="p-3 bg-muted/50 rounded-lg">
              <div className="text-xs text-muted-foreground">Wilson 下界</div>
              <div className="text-lg font-bold">
                {block.wilson_lower === null ? '—' : `${(block.wilson_lower * 100).toFixed(1)}%`}
              </div>
            </div>
            <div className="p-3 bg-muted/50 rounded-lg">
              <div className="text-xs text-muted-foreground">事件数</div>
              <div className="text-lg font-bold">{block.events}</div>
            </div>
            <div className="p-3 bg-muted/50 rounded-lg">
              <div className="text-xs text-muted-foreground">平均前向收益</div>
              <div
                className={`text-lg font-bold ${(block.avg_forward_return ?? 0) >= 0 ? 'text-green-500' : 'text-red-500'}`}
              >
                {block.avg_forward_return === undefined
                  ? '—'
                  : pct(block.avg_forward_return)}
              </div>
            </div>
          </div>

          {years.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="py-2 pr-4 font-medium">年份</th>
                    <th className="py-2 pr-4 font-medium">事件数</th>
                    <th className="py-2 pr-4 font-medium">命中率</th>
                  </tr>
                </thead>
                <tbody>
                  {years.map((y) => (
                    <tr key={y} className="border-b">
                      <td className="py-2 pr-4">{y}</td>
                      <td className="py-2 pr-4">{block.by_year[y].events}</td>
                      <td
                        className={`py-2 pr-4 font-medium ${hitRateColor(block.by_year[y].hit_rate)}`}
                      >
                        {(block.by_year[y].hit_rate * 100).toFixed(1)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function horizonVerdict(block: CalibrationHorizon): { text: string; cls: string } {
  if (block.hit_rate === null) {
    return { text: '无成熟事件', cls: 'text-amber-600 dark:text-amber-400' }
  }
  if (block.wilson_lower !== null && block.wilson_lower > 0.5) {
    return {
      text: '保守下界仍在 50% 之上——命中率经得起样本量折减',
      cls: 'text-emerald-600 dark:text-emerald-400',
    }
  }
  if (block.hit_rate < 0.5) {
    return { text: '历史命中率不足一半——入场信号更常错误', cls: 'text-red-500' }
  }
  return {
    text: '命中率过半但保守下界未过半——样本量还不足以确证优势',
    cls: 'text-amber-600 dark:text-amber-400',
  }
}

function hitRateColor(rate: number): string {
  if (rate > 0.5) return 'text-emerald-600 dark:text-emerald-400'
  if (rate < 0.5) return 'text-red-500'
  return ''
}

function pct(value: number, digits = 1): string {
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(digits)}%`
}

function formatParams(params: Record<string, number>): string {
  return Object.entries(params)
    .map(([name, value]) => `${name}=${value}`)
    .join(' · ')
}

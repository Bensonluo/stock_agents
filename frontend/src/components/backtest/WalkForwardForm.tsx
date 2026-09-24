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
import { Loader2, Play } from 'lucide-react'
import {
  API,
  type StrategiesResponse,
  type WalkForwardAggregate,
  type WalkForwardRequest,
  type WalkForwardResponse,
} from '@/lib/utils'

// buy_and_hold has no tunable parameters: a single-configuration "search"
// carries no selection pressure, so the DSR (and this panel) excludes it.
const TUNABLE_STRATEGIES = new Set(['sma_crossover', 'rsi_strategy', 'macd_strategy'])

export function WalkForwardForm() {
  const [strategies, setStrategies] = useState<StrategiesResponse | null>(null)
  const [symbol, setSymbol] = useState('AAPL')
  const [strategy, setStrategy] = useState('sma_crossover')
  const [market, setMarket] = useState<'us' | 'cn'>('us')
  const [selectionMetric, setSelectionMetric] = useState<'sharpe' | 'cagr'>('sharpe')
  const [startDate, setStartDate] = useState('2021-01-01')
  const [endDate, setEndDate] = useState('2024-01-01')
  const [initialCash, setInitialCash] = useState('10000')
  const [trainBars, setTrainBars] = useState('150')
  const [testBars, setTestBars] = useState('75')
  const [smaShort, setSmaShort] = useState('5, 10, 20')
  const [smaLong, setSmaLong] = useState('40, 60')
  const [rsiPeriod, setRsiPeriod] = useState('7, 14')
  const [rsiOverbought, setRsiOverbought] = useState('65, 70')
  const [rsiOversold, setRsiOversold] = useState('30, 35')
  const [fastPeriod, setFastPeriod] = useState('8, 12')
  const [slowPeriod, setSlowPeriod] = useState('21, 26')
  const [signalPeriod, setSignalPeriod] = useState('7, 9')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<WalkForwardResponse | null>(null)
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
      const rawGrid: Record<string, string> =
        strategy === 'sma_crossover'
          ? { sma_short: smaShort, sma_long: smaLong }
          : strategy === 'rsi_strategy'
            ? { rsi_period: rsiPeriod, rsi_overbought: rsiOverbought, rsi_oversold: rsiOversold }
            : { fast_period: fastPeriod, slow_period: slowPeriod, signal_period: signalPeriod }

      const param_grid: Record<string, number[]> = {}
      for (const [name, raw] of Object.entries(rawGrid)) {
        const values = raw
          .split(',')
          .map((s) => s.trim())
          .filter((s) => s.length > 0)
          .map(Number)
        if (values.length === 0 || values.some((v) => !Number.isFinite(v))) {
          throw new Error(`参数 ${name} 的候选列表无效——请输入逗号分隔的数字（如 5, 10, 20）`)
        }
        param_grid[name] = values
      }

      const request: WalkForwardRequest = {
        symbol: symbol.toUpperCase(),
        strategy: strategy as WalkForwardRequest['strategy'],
        start_date: startDate,
        end_date: endDate,
        param_grid,
        train_bars: parseInt(trainBars, 10),
        test_bars: parseInt(testBars, 10),
        initial_cash: parseFloat(initialCash),
        market,
        selection_metric: selectionMetric,
      }

      setResult(await API.runWalkForward(request))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Walk-forward failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Play className="h-5 w-5" />
            Walk-forward 选参
          </CardTitle>
          <CardDescription>
            滚动训练/测试窗口 · 训练段选参、测试段验证 · 结果含参数稳定性与折减 Sharpe（DSR）
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="wf-symbol">Stock Symbol</Label>
                <Input
                  id="wf-symbol"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                  disabled={loading}
                  placeholder="AAPL / 600000"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="wf-strategy">Strategy</Label>
                <Select value={strategy} onValueChange={setStrategy} disabled={loading}>
                  <SelectTrigger id="wf-strategy">
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
                <Label htmlFor="wf-market">Market</Label>
                <Select
                  value={market}
                  onValueChange={(v) => setMarket(v as 'us' | 'cn')}
                  disabled={loading}
                >
                  <SelectTrigger id="wf-market">
                    <SelectValue placeholder="Select market" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="us">美股 (US)</SelectItem>
                    <SelectItem value="cn">A股 (CN)</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="wf-metric">选参指标（训练段）</Label>
                <Select
                  value={selectionMetric}
                  onValueChange={(v) => setSelectionMetric(v as 'sharpe' | 'cagr')}
                  disabled={loading}
                >
                  <SelectTrigger id="wf-metric">
                    <SelectValue placeholder="Select metric" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="sharpe">Sharpe</SelectItem>
                    <SelectItem value="cagr">CAGR</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="wf-start">Start Date</Label>
                <Input
                  id="wf-start"
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  disabled={loading}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="wf-end">End Date</Label>
                <Input
                  id="wf-end"
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  disabled={loading}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="wf-train">训练窗口（根）</Label>
                <Input
                  id="wf-train"
                  type="number"
                  value={trainBars}
                  onChange={(e) => setTrainBars(e.target.value)}
                  disabled={loading}
                  min="50"
                  step="25"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="wf-test">测试窗口（根）</Label>
                <Input
                  id="wf-test"
                  type="number"
                  value={testBars}
                  onChange={(e) => setTestBars(e.target.value)}
                  disabled={loading}
                  min="10"
                  step="5"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="wf-cash">Initial Cash</Label>
                <Input
                  id="wf-cash"
                  type="number"
                  value={initialCash}
                  onChange={(e) => setInitialCash(e.target.value)}
                  disabled={loading}
                  min="1000"
                  step="1000"
                />
              </div>

              {strategy === 'sma_crossover' && (
                <>
                  <div className="space-y-2">
                    <Label htmlFor="wf-sma-short">Short Period 候选</Label>
                    <Input
                      id="wf-sma-short"
                      value={smaShort}
                      onChange={(e) => setSmaShort(e.target.value)}
                      disabled={loading}
                      placeholder="5, 10, 20"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="wf-sma-long">Long Period 候选</Label>
                    <Input
                      id="wf-sma-long"
                      value={smaLong}
                      onChange={(e) => setSmaLong(e.target.value)}
                      disabled={loading}
                      placeholder="40, 60"
                    />
                  </div>
                </>
              )}

              {strategy === 'rsi_strategy' && (
                <>
                  <div className="space-y-2">
                    <Label htmlFor="wf-rsi-period">RSI Period 候选</Label>
                    <Input
                      id="wf-rsi-period"
                      value={rsiPeriod}
                      onChange={(e) => setRsiPeriod(e.target.value)}
                      disabled={loading}
                      placeholder="7, 14"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="wf-rsi-ob">Overbought 候选</Label>
                    <Input
                      id="wf-rsi-ob"
                      value={rsiOverbought}
                      onChange={(e) => setRsiOverbought(e.target.value)}
                      disabled={loading}
                      placeholder="65, 70"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="wf-rsi-os">Oversold 候选</Label>
                    <Input
                      id="wf-rsi-os"
                      value={rsiOversold}
                      onChange={(e) => setRsiOversold(e.target.value)}
                      disabled={loading}
                      placeholder="30, 35"
                    />
                  </div>
                </>
              )}

              {strategy === 'macd_strategy' && (
                <>
                  <div className="space-y-2">
                    <Label htmlFor="wf-fast">Fast EMA 候选</Label>
                    <Input
                      id="wf-fast"
                      value={fastPeriod}
                      onChange={(e) => setFastPeriod(e.target.value)}
                      disabled={loading}
                      placeholder="8, 12"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="wf-slow">Slow EMA 候选</Label>
                    <Input
                      id="wf-slow"
                      value={slowPeriod}
                      onChange={(e) => setSlowPeriod(e.target.value)}
                      disabled={loading}
                      placeholder="21, 26"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="wf-signal">Signal EMA 候选</Label>
                    <Input
                      id="wf-signal"
                      value={signalPeriod}
                      onChange={(e) => setSignalPeriod(e.target.value)}
                      disabled={loading}
                      placeholder="7, 9"
                    />
                  </div>
                </>
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
                  Running Walk-forward...
                </>
              ) : (
                <>
                  <Play className="mr-2 h-4 w-4" />
                  Run Walk-forward
                </>
              )}
            </Button>
          </form>
        </CardContent>
      </Card>

      {result && <WalkForwardResult result={result} />}
    </div>
  )
}

interface WalkForwardResultProps {
  result: WalkForwardResponse
}

function WalkForwardResult({ result }: WalkForwardResultProps) {
  const { aggregate, windows, configs_tested } = result

  if (aggregate.error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Walk-forward 结果</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-sm font-semibold text-amber-600 dark:text-amber-400">
            {aggregate.error}
          </div>
          <div className="text-xs text-muted-foreground mt-1">
            加长日期区间或缩短训练/测试窗口后重试
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Walk-forward 结果</span>
          <span className="text-sm font-normal text-muted-foreground">
            搜索 {configs_tested} 个配置 · {windows.length} 个窗口
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="p-4 bg-muted/50 rounded-lg">
            <div className="text-sm text-muted-foreground">OOS 平均收益/窗</div>
            <div
              className={`text-xl font-bold ${(aggregate.oos_return_mean ?? 0) >= 0 ? 'text-green-500' : 'text-red-500'}`}
            >
              {aggregate.oos_return_mean === null ? '—' : pct(aggregate.oos_return_mean)}
            </div>
          </div>
          <div className="p-4 bg-muted/50 rounded-lg">
            <div className="text-sm text-muted-foreground">OOS 平均 Sharpe</div>
            <div className="text-xl font-bold">
              {aggregate.oos_sharpe_mean === null ? '—' : aggregate.oos_sharpe_mean.toFixed(2)}
            </div>
          </div>
          <div className="p-4 bg-muted/50 rounded-lg">
            <div className="text-sm text-muted-foreground">亏损窗口</div>
            <div className="text-xl font-bold">
              {aggregate.losing_windows} / {aggregate.windows_run}
            </div>
          </div>
          <div className="p-4 bg-muted/50 rounded-lg">
            <div className="text-sm text-muted-foreground">参数稳定性</div>
            <div className="text-xl font-bold">
              {aggregate.param_stability === null
                ? '—'
                : `${(aggregate.param_stability * 100).toFixed(1)}%`}
            </div>
          </div>
          <div className="p-4 bg-muted/50 rounded-lg">
            <div className="text-sm text-muted-foreground">最差窗口</div>
            <div
              className={`text-xl font-bold ${aggregate.worst_window && aggregate.worst_window.test_return < 0 ? 'text-red-500' : 'text-green-500'}`}
            >
              {aggregate.worst_window === null ? '—' : pct(aggregate.worst_window.test_return)}
            </div>
          </div>
        </div>

        <DeflatedSharpeCard dsr={aggregate.deflated_sharpe} />

        <div className="space-y-2">
          <div className="text-sm font-medium">逐窗口明细</div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-2 pr-4 font-medium">测试窗口</th>
                  <th className="py-2 pr-4 font-medium">选中参数</th>
                  <th className="py-2 pr-4 font-medium">训练分</th>
                  <th className="py-2 pr-4 font-medium">OOS 收益</th>
                </tr>
              </thead>
              <tbody>
                {windows.map((w) => (
                  <tr key={`${w.test_start}-${w.test_end}`} className="border-b">
                    <td className="py-2 pr-4 whitespace-nowrap">
                      {w.test_start.slice(0, 10)} ~ {w.test_end.slice(0, 10)}
                    </td>
                    <td className="py-2 pr-4 text-muted-foreground">{formatParams(w.chosen_params)}</td>
                    <td className="py-2 pr-4">{w.train_score === null ? '—' : w.train_score.toFixed(2)}</td>
                    <td
                      className={`py-2 pr-4 font-medium ${w.test_return !== null && w.test_return < 0 ? 'text-red-500' : 'text-emerald-600 dark:text-emerald-400'}`}
                    >
                      {w.test_return === null ? '—' : pct(w.test_return)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function DeflatedSharpeCard({ dsr }: { dsr: WalkForwardAggregate['deflated_sharpe'] }) {
  if (!dsr) {
    return (
      <div className="space-y-2 pt-2 border-t">
        <div>
          <div className="text-sm font-medium">折减 Sharpe（DSR）</div>
          <div className="text-xs text-muted-foreground">
            Bailey &amp; López de Prado (2014)：选参赢家须跑赢 N 次搜索的期望噪音上限
          </div>
        </div>
        <div className="text-sm font-semibold text-amber-600 dark:text-amber-400">
          样本不足以计算 DSR（单一配置 / 无搜索离散度 / OOS 序列过短）——如实拒绝而非捏造
        </div>
      </div>
    )
  }

  const isSignificant = dsr.dsr >= 0.95
  const isDeflated = dsr.dsr <= 0.05
  const verdict = isSignificant
    ? {
        text: '折减选参偏差后 Sharpe 仍显著为正——选参结果可信',
        cls: 'text-emerald-600 dark:text-emerald-400',
      }
    : isDeflated
      ? { text: '选参优势在折减后消失——大概率是搜索幸存者', cls: 'text-red-500' }
      : { text: '尚不能把该 Sharpe 与选参噪音区分开', cls: 'text-amber-600 dark:text-amber-400' }

  return (
    <div className="space-y-3 pt-2 border-t">
      <div>
        <div className="text-sm font-medium">折减 Sharpe（DSR）</div>
        <div className="text-xs text-muted-foreground">
          Bailey &amp; López de Prado (2014)：选参赢家须跑赢 N 次搜索的期望噪音上限
        </div>
      </div>
      <div className={`text-sm font-semibold ${verdict.cls}`}>{verdict.text}</div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="p-3 bg-muted/50 rounded-lg">
          <div className="text-xs text-muted-foreground">DSR</div>
          <div className="text-lg font-bold">{(dsr.dsr * 100).toFixed(1)}%</div>
        </div>
        <div className="p-3 bg-muted/50 rounded-lg">
          <div className="text-xs text-muted-foreground">OOS Sharpe（年化）</div>
          <div className="text-lg font-bold">{dsr.sharpe_annualized.toFixed(2)}</div>
        </div>
        <div className="p-3 bg-muted/50 rounded-lg">
          <div className="text-xs text-muted-foreground">噪音上限 SR₀（年化）</div>
          <div className="text-lg font-bold">{dsr.sr0_annualized.toFixed(2)}</div>
        </div>
        <div className="p-3 bg-muted/50 rounded-lg">
          <div className="text-xs text-muted-foreground">搜索宽度</div>
          <div className="text-lg font-bold">{dsr.n_trials} 配置</div>
        </div>
      </div>
      <div className="text-xs text-muted-foreground">
        Trial Sharpe 离散 ±{dsr.trial_sharpe_std_annualized.toFixed(2)} · OOS {dsr.oos_bars} 根 ·
        偏度 {dsr.skew.toFixed(2)} · 峰度 {dsr.kurtosis.toFixed(2)}
      </div>
    </div>
  )
}

function pct(value: number, digits = 1): string {
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(digits)}%`
}

function formatParams(params: Record<string, number>): string {
  return Object.entries(params)
    .map(([name, value]) => `${name}=${value}`)
    .join(' · ')
}

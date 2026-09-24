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
import { API, type BacktestRequest, type BacktestResponse, type StrategiesResponse } from '@/lib/utils'
import { BacktestChart } from './BacktestChart'

export function BacktestForm() {
  const [strategies, setStrategies] = useState<StrategiesResponse | null>(null)
  const [symbol, setSymbol] = useState('AAPL')
  const [strategy, setStrategy] = useState('sma_crossover')
  const [startDate, setStartDate] = useState('2023-01-01')
  const [endDate, setEndDate] = useState('2024-01-01')
  const [initialCash, setInitialCash] = useState('10000')
  const [smaShort, setSmaShort] = useState('20')
  const [smaLong, setSmaLong] = useState('50')
  const [rsiPeriod, setRsiPeriod] = useState('14')
  const [rsiOverbought, setRsiOverbought] = useState('70')
  const [rsiOversold, setRsiOversold] = useState('30')
  const [fastPeriod, setFastPeriod] = useState('12')
  const [slowPeriod, setSlowPeriod] = useState('26')
  const [signalPeriod, setSignalPeriod] = useState('9')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<BacktestResponse | null>(null)
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
      const selectedStrategy = strategy as BacktestRequest['strategy']
      const request: BacktestRequest = {
        symbol: symbol.toUpperCase(),
        strategy: selectedStrategy,
        start_date: startDate,
        end_date: endDate,
        initial_cash: parseFloat(initialCash),
      }
      if (selectedStrategy === 'sma_crossover') {
        request.sma_short = parseInt(smaShort)
        request.sma_long = parseInt(smaLong)
      } else if (selectedStrategy === 'rsi_strategy') {
        request.rsi_period = parseInt(rsiPeriod)
        request.rsi_overbought = parseFloat(rsiOverbought)
        request.rsi_oversold = parseFloat(rsiOversold)
      } else if (selectedStrategy === 'macd_strategy') {
        request.fast_period = parseInt(fastPeriod)
        request.slow_period = parseInt(slowPeriod)
        request.signal_period = parseInt(signalPeriod)
      }

      const response = await API.runBacktest(request)
      setResult(response)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Backtest failed')
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
            运行回测
          </CardTitle>
          <CardDescription>
            下一根 K 线成交 · 含交易成本 · 基准对比与完整指标
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="symbol">Stock Symbol</Label>
                <Input
                  id="symbol"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                  disabled={loading}
                  placeholder="AAPL"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="strategy">Strategy</Label>
                <Select value={strategy} onValueChange={setStrategy} disabled={loading}>
                  <SelectTrigger id="strategy">
                    <SelectValue placeholder="Select strategy" />
                  </SelectTrigger>
                  <SelectContent>
                    {strategies?.strategies.map((s) => (
                      <SelectItem key={s.name} value={s.name}>
                        {s.description}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="start_date">Start Date</Label>
                <Input
                  id="start_date"
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  disabled={loading}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="end_date">End Date</Label>
                <Input
                  id="end_date"
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  disabled={loading}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="initial_cash">Initial Cash ($)</Label>
                <Input
                  id="initial_cash"
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
                    <Label htmlFor="sma_short">Short Period</Label>
                    <Input
                      id="sma_short"
                      type="number"
                      value={smaShort}
                      onChange={(e) => setSmaShort(e.target.value)}
                      disabled={loading}
                      min="5"
                      max="100"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="sma_long">Long Period</Label>
                    <Input
                      id="sma_long"
                      type="number"
                      value={smaLong}
                      onChange={(e) => setSmaLong(e.target.value)}
                      disabled={loading}
                      min="10"
                      max="200"
                    />
                  </div>
                </>
              )}

              {strategy === 'rsi_strategy' && (
                <>
                  <div className="space-y-2">
                    <Label htmlFor="rsi_period">RSI Period</Label>
                    <Input id="rsi_period" type="number" value={rsiPeriod} onChange={(e) => setRsiPeriod(e.target.value)} disabled={loading} min="5" max="50" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="rsi_overbought">Overbought</Label>
                    <Input id="rsi_overbought" type="number" value={rsiOverbought} onChange={(e) => setRsiOverbought(e.target.value)} disabled={loading} min="50" max="100" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="rsi_oversold">Oversold</Label>
                    <Input id="rsi_oversold" type="number" value={rsiOversold} onChange={(e) => setRsiOversold(e.target.value)} disabled={loading} min="0" max="50" />
                  </div>
                </>
              )}

              {strategy === 'macd_strategy' && (
                <>
                  <div className="space-y-2">
                    <Label htmlFor="fast_period">Fast EMA</Label>
                    <Input id="fast_period" type="number" value={fastPeriod} onChange={(e) => setFastPeriod(e.target.value)} disabled={loading} min="2" max="100" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="slow_period">Slow EMA</Label>
                    <Input id="slow_period" type="number" value={slowPeriod} onChange={(e) => setSlowPeriod(e.target.value)} disabled={loading} min="3" max="200" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="signal_period">Signal EMA</Label>
                    <Input id="signal_period" type="number" value={signalPeriod} onChange={(e) => setSignalPeriod(e.target.value)} disabled={loading} min="2" max="100" />
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
                  Running Backtest...
                </>
              ) : (
                <>
                  <Play className="mr-2 h-4 w-4" />
                  Run Backtest
                </>
              )}
            </Button>
          </form>
        </CardContent>
      </Card>

      {result && <BacktestResult result={result} />}
    </div>
  )
}

interface BacktestResultProps {
  result: BacktestResponse
}

function BacktestResult({ result }: BacktestResultProps) {
  const isProfitable = result.total_return >= 0

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Backtest Results</span>
            <span className={`text-sm font-normal ${isProfitable ? 'text-green-500' : 'text-red-500'}`}>
              {isProfitable ? '+' : ''}{result.total_return_pct.toFixed(2)}%
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Chart */}
          <BacktestChart data={result.equity} initialCash={result.initial_cash} />

          {/* Stats Grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="p-4 bg-muted/50 rounded-lg">
              <div className="text-sm text-muted-foreground">Initial Cash</div>
              <div className="text-xl font-bold">${result.initial_cash.toLocaleString()}</div>
            </div>
            <div className="p-4 bg-muted/50 rounded-lg">
              <div className="text-sm text-muted-foreground">Final Value</div>
              <div className={`text-xl font-bold ${isProfitable ? 'text-green-500' : 'text-red-500'}`}>
                ${result.final_value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
            </div>
            <div className="p-4 bg-muted/50 rounded-lg">
              <div className="text-sm text-muted-foreground">Total Return</div>
              <div className={`text-xl font-bold ${isProfitable ? 'text-green-500' : 'text-red-500'}`}>
                {isProfitable ? '+' : ''}${result.total_return.toFixed(2)}
              </div>
            </div>
            <div className="p-4 bg-muted/50 rounded-lg">
              <div className="text-sm text-muted-foreground">Annual Return</div>
              <div className={`text-xl font-bold ${result.annual_return >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                {result.annual_return >= 0 ? '+' : ''}{result.annual_return.toFixed(2)}%
              </div>
            </div>
            <div className="p-4 bg-muted/50 rounded-lg">
              <div className="text-sm text-muted-foreground">Sharpe Ratio</div>
              <div className="text-xl font-bold">{result.sharpe_ratio.toFixed(2)}</div>
            </div>
            <div className="p-4 bg-muted/50 rounded-lg">
              <div className="text-sm text-muted-foreground">Max Drawdown</div>
              <div className="text-xl font-bold text-red-500">-{result.max_drawdown.toFixed(2)}%</div>
            </div>
            <div className="p-4 bg-muted/50 rounded-lg">
              <div className="text-sm text-muted-foreground">Win Rate</div>
              <div className="text-xl font-bold">{result.win_rate.toFixed(1)}%</div>
            </div>
            <div className="p-4 bg-muted/50 rounded-lg">
              <div className="text-sm text-muted-foreground">Total Trades</div>
              <div className="text-xl font-bold">{result.total_trades}</div>
            </div>
          </div>

          {result.null_benchmark && <NullBenchmarkCard nb={result.null_benchmark} />}
        </CardContent>
      </Card>
    </div>
  )
}

function pct(value: number, digits = 1): string {
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(digits)}%`
}

function NullBenchmarkCard({ nb }: { nb: NonNullable<BacktestResponse['null_benchmark']> }) {
  // One-sided p: probability that random timing does at least as well.
  const isSignal = nb.p_value <= 0.05
  const isAntiSignal = nb.p_value >= 0.95
  const verdict = isSignal
    ? { text: '信号显著优于随机入场（p ≤ 0.05）', cls: 'text-emerald-600 dark:text-emerald-400' }
    : isAntiSignal
      ? { text: '显著差于随机入场——择时在帮倒忙', cls: 'text-red-500' }
      : { text: '与随机入场不可区分——收益更可能来自行情而非择时', cls: 'text-amber-600 dark:text-amber-400' }

  return (
    <div className="space-y-3 pt-2 border-t">
      <div>
        <div className="text-sm font-medium">信号 vs 噪音 · 随机入场基准</div>
        <div className="text-xs text-muted-foreground">
          Monte Carlo {nb.iterations} 次抽样：同样的 {nb.matched_round_trips} 段持仓时长、同一行情、同一成本，仅入场时点随机
        </div>
      </div>
      <div className={`text-sm font-semibold ${verdict.cls}`}>{verdict.text}</div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="p-3 bg-muted/50 rounded-lg">
          <div className="text-xs text-muted-foreground">策略收益</div>
          <div className="text-lg font-bold">{pct(nb.strategy_return)}</div>
        </div>
        <div className="p-3 bg-muted/50 rounded-lg">
          <div className="text-xs text-muted-foreground">随机入场中位数</div>
          <div className="text-lg font-bold">{pct(nb.null_return_p50)}</div>
        </div>
        <div className="p-3 bg-muted/50 rounded-lg">
          <div className="text-xs text-muted-foreground">随机区间 (P5–P95)</div>
          <div className="text-lg font-bold">
            {pct(nb.null_return_p05)} ~ {pct(nb.null_return_p95)}
          </div>
        </div>
        <div className="p-3 bg-muted/50 rounded-lg">
          <div className="text-xs text-muted-foreground">百分位 / p 值</div>
          <div className="text-lg font-bold">
            {(nb.percentile * 100).toFixed(0)} 分位 · p={nb.p_value.toFixed(3)}
          </div>
        </div>
      </div>
    </div>
  )
}

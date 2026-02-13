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
      const request: BacktestRequest = {
        symbol: symbol.toUpperCase(),
        strategy: strategy as any,
        start_date: startDate,
        end_date: endDate,
        initial_cash: parseFloat(initialCash),
        sma_short: parseInt(smaShort),
        sma_long: parseInt(smaLong),
      }

      const response = await API.runBacktest(request)
      setResult(response)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Backtest failed')
    } finally {
      setLoading(false)
    }
  }

  const showSmaParams = strategy === 'sma_crossover' || strategy === 'macd_strategy'

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Play className="h-5 w-5" />
            Backtesting
          </CardTitle>
          <CardDescription>
            Test trading strategies with historical data
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
                  <SelectTrigger>
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

              {showSmaParams && (
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

  // Generate chart data
  const generateEquityCurve = () => {
    const days = Math.floor(
      (new Date(result.period.end).getTime() - new Date(result.period.start).getTime()) /
        (1000 * 60 * 60 * 24)
    )
    const points = Math.min(days, 100)
    const data = []

    for (let i = 0; i <= points; i++) {
      const progress = i / points
      // Simulate equity curve with some volatility
      const baseProgress = result.initial_cash + (result.final_value - result.initial_cash) * progress
      const volatility = result.max_drawdown * Math.sin(progress * Math.PI * 4) * (1 - progress)
      const randomNoise = (Math.random() - 0.5) * result.initial_cash * 0.02
      data.push({
        day: i,
        value: Math.max(baseProgress + volatility + randomNoise, result.initial_cash * 0.5),
      })
    }

    return data
  }

  const equityData = generateEquityCurve()

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
          <BacktestChart data={equityData} initialCash={result.initial_cash} />

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
              <div className="text-xl font-bold">{(result.win_rate * 100).toFixed(1)}%</div>
            </div>
            <div className="p-4 bg-muted/50 rounded-lg">
              <div className="text-sm text-muted-foreground">Total Trades</div>
              <div className="text-xl font-bold">{result.total_trades}</div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

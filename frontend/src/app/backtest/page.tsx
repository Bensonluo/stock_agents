'use client'

import { BacktestForm } from '@/components/backtest/BacktestForm'

export default function BacktestPage() {
  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="text-center space-y-2 mb-8">
        <h1 className="text-3xl font-bold">Backtesting</h1>
        <p className="text-muted-foreground">
          Test trading strategies with historical data to evaluate performance
        </p>
      </div>

      <BacktestForm />
    </div>
  )
}

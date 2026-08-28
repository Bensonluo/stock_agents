'use client'

import { BacktestForm } from '@/components/backtest/BacktestForm'

export default function BacktestPage() {
  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="text-center space-y-2 mb-8">
        <h1 className="text-3xl font-bold">策略回测</h1>
        <p className="text-muted-foreground">
          V2 确定性引擎:信号下一根 K 线成交、计入佣金与滑点、期末强制平仓——结果附完整指标与可复现 manifest
        </p>
      </div>

      <BacktestForm />
    </div>
  )
}

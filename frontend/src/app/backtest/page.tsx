'use client'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { BacktestForm } from '@/components/backtest/BacktestForm'
import { WalkForwardForm } from '@/components/backtest/WalkForwardForm'
import { CalibrationForm } from '@/components/backtest/CalibrationForm'

export default function BacktestPage() {
  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="text-center space-y-2 mb-8">
        <h1 className="text-3xl font-bold">策略回测</h1>
        <p className="text-muted-foreground">
          V2 确定性引擎:信号下一根 K 线成交、计入佣金与滑点、期末强制平仓——结果附完整指标与可复现 manifest
        </p>
      </div>

      <Tabs defaultValue="single" className="w-full">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="single">单次回测</TabsTrigger>
          <TabsTrigger value="walkforward">Walk-forward 选参</TabsTrigger>
          <TabsTrigger value="calibrate">信号校准</TabsTrigger>
        </TabsList>
        <TabsContent value="single" className="mt-4">
          <BacktestForm />
        </TabsContent>
        <TabsContent value="walkforward" className="mt-4">
          <WalkForwardForm />
        </TabsContent>
        <TabsContent value="calibrate" className="mt-4">
          <CalibrationForm />
        </TabsContent>
      </Tabs>
    </div>
  )
}

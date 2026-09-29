'use client'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { FlaskConical, Play, Repeat, Target } from 'lucide-react'
import { BacktestForm } from '@/components/backtest/BacktestForm'
import { WalkForwardForm } from '@/components/backtest/WalkForwardForm'
import { CalibrationForm } from '@/components/backtest/CalibrationForm'

export default function BacktestPage() {
  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="text-center space-y-3 mb-8 pt-4">
        <div className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-600 to-indigo-600 shadow-lg shadow-blue-600/20">
          <FlaskConical className="h-6 w-6 text-white" />
        </div>
        <h1 className="text-3xl font-bold tracking-tight">策略回测</h1>
        <p className="text-muted-foreground text-balance max-w-2xl mx-auto">
          V2 确定性引擎:信号下一根 K 线成交、计入佣金与滑点、期末强制平仓——结果附完整指标与可复现 manifest
        </p>
      </div>

      <Tabs defaultValue="single" className="w-full">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="single" className="flex items-center gap-1.5">
            <Play className="h-4 w-4" />
            单次回测
          </TabsTrigger>
          <TabsTrigger value="walkforward" className="flex items-center gap-1.5">
            <Repeat className="h-4 w-4" />
            Walk-forward 选参
          </TabsTrigger>
          <TabsTrigger value="calibrate" className="flex items-center gap-1.5">
            <Target className="h-4 w-4" />
            信号校准
          </TabsTrigger>
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

'use client'

import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'
import { OptionImpliedBlock } from './report-shared'
import type { OptionImplied } from './types'

// 风险评估组件
export function RiskAssessment({ data }: { data: any }) {
  if (!data || typeof data !== 'object') return <p className="text-slate-500">暂无数据</p>

  // 安全获取风险等级，确保是字符串
  const getRiskLevel = (): string => {
    const raw = data.overall_risk_level || data.risk_level || data.overall || 'medium'
    if (typeof raw === 'string') return raw
    if (typeof raw === 'number') return raw >= 70 ? 'high' : raw >= 30 ? 'medium' : 'low'
    return 'medium'
  }

  const level = getRiskLevel()
  const factors = Array.isArray(data.risk_factors) ? data.risk_factors : []

  const getRiskInfo = (riskLevel: string) => {
    const r = String(riskLevel).toLowerCase()
    if (r.includes('low')) return { text: '低风险', color: 'text-green-600', bg: 'bg-green-100', progress: 25 }
    if (r.includes('high')) return { text: '高风险', color: 'text-red-600', bg: 'bg-red-100', progress: 75 }
    return { text: '中等风险', color: 'text-amber-600', bg: 'bg-amber-100', progress: 50 }
  }

  const info = getRiskInfo(level)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={cn("px-3 py-1 rounded-full text-sm font-medium", info.bg, info.color)}>
            {info.text}
          </div>
        </div>
        <Progress value={info.progress} className="w-24 h-2" />
      </div>

      {factors.length > 0 && (
        <div>
          <p className="text-sm text-slate-500 mb-2">风险因素</p>
          <ul className="space-y-1">
            {factors.slice(0, 5).map((factor: string, i: number) => (
              <li key={i} className="text-sm flex items-start gap-2">
                <span className="text-amber-500 mt-0.5">•</span>
                {factor}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 期权隐含情绪标注 —— pipeline 形状键恒在、值可 null（无 CN 快照时），
          与 ReAct 视图共用同一渲染块 */}
      {typeof data.option_implied === 'object' && data.option_implied !== null && (
        <OptionImpliedBlock block={data.option_implied as OptionImplied} />
      )}
    </div>
  )
}

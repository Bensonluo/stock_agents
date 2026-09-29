'use client'

import type { ReactNode } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

/* ReactReport 的共享格式化器与 SectionCard —— 从组件内提取的纯函数
 * （不闭包组件状态；filterEntries 因闭包 activeSymbol 留在组件内）。 */

export const actionZh = (a: string): string => {
  const m: Record<string, string> = {
    buy: '买入', add: '加仓', hold: '持有', reduce: '减仓', sell: '卖出',
    strong_buy: '强烈买入', strong_sell: '强烈卖出',
  }
  return m[String(a || '').toLowerCase()] || a || '持有'
}

export const actionStyle = (a: string) => {
  const s = String(a || '').toLowerCase()
  if (['buy', 'add', 'strong_buy'].includes(s))
    return { ring: 'ring-green-200', color: 'text-green-700', bg: 'bg-green-100' }
  if (['sell', 'reduce', 'strong_sell'].includes(s))
    return { ring: 'ring-red-200', color: 'text-red-700', bg: 'bg-red-100' }
  return { ring: 'ring-amber-200', color: 'text-amber-700', bg: 'bg-amber-100' }
}

export const trendZh = (t: string): string => {
  const s = String(t || '').toLowerCase()
  if (s.includes('bull') || s.includes('buy')) return '看涨'
  if (s.includes('bear') || s.includes('sell')) return '看跌'
  return '中性'
}

export const trendColor = (t: string): string => {
  const s = String(t || '').toLowerCase()
  if (s.includes('bull') || s.includes('buy')) return 'text-green-600'
  if (s.includes('bear') || s.includes('sell')) return 'text-red-600'
  return 'text-amber-600'
}

export const riskZh = (r: string): string => {
  const m: Record<string, string> = { very_low: '极低', low: '低', medium: '中', high: '高', very_high: '极高' }
  return m[String(r || '').toLowerCase()] || r || '中'
}

export const riskStyle = (r: string) => {
  const s = String(r || '').toLowerCase()
  if (['very_low', 'low'].includes(s)) return { color: 'text-green-700', bg: 'bg-green-100' }
  if (['high', 'very_high'].includes(s)) return { color: 'text-red-700', bg: 'bg-red-100' }
  return { color: 'text-amber-700', bg: 'bg-amber-100' }
}

export const sentimentZh = (s: string): string => {
  const v = String(s || '').toLowerCase()
  if (v.includes('very_positive')) return '非常积极'
  if (v.includes('positive')) return '积极'
  if (v.includes('very_negative')) return '非常消极'
  if (v.includes('negative')) return '消极'
  return '中性'
}

export const scoreOf = (v: any): number | null => {
  if (typeof v === 'number') return v
  if (v && typeof v === 'object' && typeof v.score === 'number') return v.score
  return null
}

export const SectionCard = ({ icon: Icon, title, children }: { icon: any; title: string; children: ReactNode }) => (
  <Card>
    <CardHeader className="pb-3">
      <CardTitle className="text-base flex items-center gap-2">
        <Icon className="h-4 w-4 text-slate-500" />
        {title}
      </CardTitle>
    </CardHeader>
    <CardContent>{children}</CardContent>
  </Card>
)

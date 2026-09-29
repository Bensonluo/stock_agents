'use client'

import { Button } from '@/components/ui/button'
import { formatNumber } from '@/lib/format'

// 分析详情组件
export function AnalysisDetail({ data, expanded, onToggle }: { data: any; expanded: boolean; onToggle: () => void }) {
  if (!data || typeof data !== 'object') return <p className="text-slate-500">暂无数据</p>

  // 提取关键指标
  const keyMetrics: { label: string; value: string | number }[] = []

  // 常见的技术/基本面指标
  const metricLabels: Record<string, string> = {
    'rsi': 'RSI',
    'macd': 'MACD',
    'sma_20': '20日均线',
    'sma_50': '50日均线',
    'trend': '趋势',
    'pe_ratio': '市盈率',
    'pb_ratio': '市净率',
    'revenue_growth': '营收增长',
    'eps': '每股收益',
    'roe': '净资产收益率',
    'debt_to_equity': '负债率',
    'overall': '综合评价',
    'signal': '信号',
    'recommendation': '建议',
  }

  const extractMetrics = (obj: any, prefix = '') => {
    for (const [key, value] of Object.entries(obj)) {
      if (typeof value === 'string' || typeof value === 'number') {
        const label = metricLabels[key] || metricLabels[prefix + key] || key.replace(/_/g, ' ')
        keyMetrics.push({
          label,
          value: typeof value === 'number' ? formatNumber(value) : value
        })
      } else if (typeof value === 'object' && value !== null) {
        extractMetrics(value, key + '_')
      }
    }
  }

  extractMetrics(data)

  const displayMetrics = expanded ? keyMetrics : keyMetrics.slice(0, 6)

  return (
    <div className="space-y-3">
      {displayMetrics.length > 0 ? (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {displayMetrics.map((metric, i) => (
              <div key={i} className="p-3 bg-slate-50 rounded-lg">
                <p className="text-xs text-slate-500 mb-1">{metric.label}</p>
                <p className="font-medium truncate">{metric.value}</p>
              </div>
            ))}
          </div>
          {keyMetrics.length > 6 && (
            <Button variant="ghost" size="sm" onClick={onToggle} className="w-full">
              {expanded ? '收起' : `查看更多 (${keyMetrics.length - 6})`}
            </Button>
          )}
        </>
      ) : (
        <p className="text-slate-500">暂无详细数据</p>
      )}
    </div>
  )
}

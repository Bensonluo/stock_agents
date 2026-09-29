'use client'

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { formatNumber } from '@/lib/format'

// 市场概览组件
export function MarketOverview({ data }: { data: any }) {
  if (!data || typeof data !== 'object') return <p className="text-slate-500">暂无数据</p>

  const symbols = data.symbols_analyzed || []
  const date = data.analysis_date

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4 text-sm">
        <span className="text-slate-500">分析日期：</span>
        <span className="font-medium">{date || '-'}</span>
      </div>

      {data.market_summary && (
        <div className="space-y-3">
          {Object.entries(data.market_summary).map(([symbol, info]: [string, any]) => (
            <div key={symbol} className="p-3 bg-slate-50 rounded-lg">
              <div className="flex items-center justify-between mb-2">
                <span className="font-medium">{info.company_name || symbol}</span>
                <Badge variant="outline">{symbol}</Badge>
              </div>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-slate-500">当前价格</span>
                  <p className="font-semibold">${info.current_price?.toFixed(2) || '-'}</p>
                </div>
                <div>
                  <span className="text-slate-500">涨跌幅</span>
                  <p className={cn(
                    "font-semibold",
                    (info.change_percent || 0) >= 0 ? "text-green-600" : "text-red-600"
                  )}>
                    {(info.change_percent || 0) >= 0 ? '+' : ''}{formatNumber(info.change_percent, 2)}%
                  </p>
                </div>
                {info.earnings?.next_earnings_date != null && (
                  <div className="col-span-2 flex justify-between">
                    <span className="text-slate-500">下次财报</span>
                    <span className={cn(
                      "font-medium",
                      info.earnings.days_until <= 7 ? "text-amber-600" : "text-slate-600"
                    )}>
                      {info.earnings.next_earnings_date}
                      <span className="ml-1 font-normal text-slate-400">
                        （{info.earnings.days_until === 0 ? '今天' : `${info.earnings.days_until} 天后`}）
                      </span>
                    </span>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

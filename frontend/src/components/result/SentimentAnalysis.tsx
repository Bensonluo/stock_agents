'use client'

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { formatNumber } from '@/lib/format'

// 情绪分析组件
export function SentimentAnalysis({ data }: { data: any }) {
  if (!data || typeof data !== 'object') return <p className="text-slate-500">暂无数据</p>

  // 安全获取情绪值，确保是字符串
  const getSentimentValue = (): string => {
    const raw = data.overall_sentiment || data.sentiment || data.overall || 'neutral'
    if (typeof raw === 'string') return raw
    if (typeof raw === 'number') return raw >= 0 ? 'positive' : 'negative'
    return 'neutral'
  }

  const overall = getSentimentValue()
  const score = typeof data.sentiment_score === 'number' ? data.sentiment_score :
                typeof data.score === 'number' ? data.score : 0
  const newsCount = data.news_count || 0

  const getSentimentInfo = (sentiment: string) => {
    const s = String(sentiment).toLowerCase()
    if (s.includes('positive') || s.includes('bullish') || s.includes('buy'))
      return { text: '积极', color: 'text-green-600', bg: 'bg-green-100' }
    if (s.includes('negative') || s.includes('bearish') || s.includes('sell'))
      return { text: '消极', color: 'text-red-600', bg: 'bg-red-100' }
    return { text: '中性', color: 'text-amber-600', bg: 'bg-amber-100' }
  }

  const info = getSentimentInfo(overall)

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <div className={cn("px-4 py-2 rounded-full", info.bg)}>
          <span className={cn("font-semibold", info.color)}>{info.text}</span>
        </div>
        {typeof score === 'number' && (
          <div className="text-sm">
            <span className="text-slate-500">情绪得分：</span>
            <span className="font-medium">{formatNumber(score, 2)}</span>
          </div>
        )}
      </div>

      {newsCount > 0 && (
        <div className="text-sm text-slate-500">
          分析了 {newsCount} 条新闻
        </div>
      )}

      {data.key_topics && Array.isArray(data.key_topics) && (
        <div>
          <p className="text-sm text-slate-500 mb-2">关键话题</p>
          <div className="flex flex-wrap gap-2">
            {data.key_topics.slice(0, 5).map((topic: string, i: number) => (
              <Badge key={i} variant="secondary">{topic}</Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

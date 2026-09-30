'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { formatNumber, formatCurrency, currencyForSymbol } from '@/lib/format'
import type { CatalystBucket, CatalystEvent, SymbolCatalysts } from './types'
import { CalendarClock, ChevronDown, ChevronUp } from 'lucide-react'

/* 催化剂时间轴 —— CN 本土惯例的类型标注纵向 feed（同花顺 F10 公司大事 /
 * 东财个股日历风格）：置顶「下一个催化剂」高亮卡 + 时间桶分组 feed +
 * 近四季 EPS 预期差迷你表。纯标注：只读 wire 上的
 * report.sections.catalysts.by_symbol[symbol]；标的既无事件也无预期差时
 * 整卡不渲染（旧报告整键缺席 → 调用方 map 为空，渲染面零扰动）。
 * 避免美式 implied-move 展示（A 股无单票期权数据）。 */

// 事件类型 → 中文标签 + chip 配色（earnings 蓝 / dividend 绿 / split 紫 /
// preannouncement 琥珀 / unlock 橙 / other 灰）；未知 type 落「其他」。
const EVENT_TYPE_CHIP: Record<string, { label: string; bg: string; color: string }> = {
  earnings: { label: '财报发布', bg: 'bg-blue-100', color: 'text-blue-700' },
  dividend: { label: '除息/分红', bg: 'bg-green-100', color: 'text-green-700' },
  split: { label: '拆股/送转', bg: 'bg-purple-100', color: 'text-purple-700' },
  preannouncement: { label: '业绩预告', bg: 'bg-amber-100', color: 'text-amber-700' },
  unlock: { label: '限售解禁', bg: 'bg-orange-100', color: 'text-orange-700' },
  other: { label: '其他', bg: 'bg-slate-100', color: 'text-slate-600' },
}

export const eventTypeChip = (type: string) =>
  EVENT_TYPE_CHIP[type] || EVENT_TYPE_CHIP.other

// 桶 → 中文标签；未知桶值并入「更远」（wire 契约只定义四桶）。
const BUCKET_ORDER = ['1w', '1m', '3m', 'later'] as const
const BUCKET_ZH: Record<CatalystBucket, string> = {
  '1w': '未来一周',
  '1m': '未来一月',
  '3m': '未来三月',
  later: '更远',
}

export const bucketZh = (bucket: string): string =>
  BUCKET_ZH[(BUCKET_ORDER as readonly string[]).includes(bucket) ? (bucket as CatalystBucket) : 'later']

// days_until → 突出显示的相对时间（0 = 今天；负值按今天兜底——wire 仅含未来事件）
export const daysUntilZh = (days: number): string =>
  !Number.isFinite(days) || days <= 0 ? '今天' : `${Math.round(days)}天后`

// 百分点数值格式化（wire 的 *_pct 约定：25 = 25%，与 formatPercent 的
// 比率约定不同，勿混用）。股息率/占流通股无符号，预期差带符号。
export const formatPctPoint = (v: number): string =>
  Number.isFinite(v) ? `${v.toFixed(1)}%` : '-'

export const formatSignedPctPoint = (v: number): string =>
  Number.isFinite(v) ? `${v >= 0 ? '+' : ''}${v.toFixed(1)}%` : '-'

// 解禁股数 CN 惯例缩写（亿股/万股）；零头原样。
export const formatShares = (n: number): string => {
  if (!Number.isFinite(n)) return '-'
  if (n >= 1e8) return `${(n / 1e8).toFixed(2)}亿股`
  if (n >= 1e4) return `${(n / 1e4).toFixed(2)}万股`
  return `${n}股`
}

// detail 字典 → 一行摘要（只认已知键，未知键静默跳过——detail 是开放字典）
export const detailLineOf = (event: CatalystEvent, symbol: string): string | null => {
  const d = event?.detail
  if (!d || typeof d !== 'object') return null
  const parts: string[] = []
  if (typeof d.amount === 'number' && Number.isFinite(d.amount))
    parts.push(`派息 ${formatCurrency(d.amount, currencyForSymbol(symbol))}`)
  if (typeof d.yield_pct === 'number' && Number.isFinite(d.yield_pct))
    parts.push(`股息率 ${formatPctPoint(d.yield_pct)}`)
  if (typeof d.shares === 'number' && Number.isFinite(d.shares))
    parts.push(`解禁 ${formatShares(d.shares)}`)
  if (typeof d.pct_of_float === 'number' && Number.isFinite(d.pct_of_float))
    parts.push(`占流通股 ${formatPctPoint(d.pct_of_float)}`)
  if (typeof d.eps_hint === 'number' && Number.isFinite(d.eps_hint))
    parts.push(`EPS 参考 ${formatNumber(d.eps_hint, 2)}`)
  return parts.length > 0 ? parts.join(' · ') : null
}

// 整卡渲染门：至少一条未来事件或一条近四季预期差才渲染（降级 run 整键缺席）
export const hasCatalystContent = (entry: SymbolCatalysts | null | undefined): boolean =>
  !!entry &&
  ((Array.isArray(entry.events) && entry.events.length > 0) ||
    (Array.isArray(entry.earnings_surprise) && entry.earnings_surprise.length > 0))

// 防御性排序：契约承诺日期升序，这里按 days_until 稳定重排（并列保日期升序），
// 非 object 行剔除（旧/新 wire 形状差异不炸渲染面）。
export const sortEvents = (events: CatalystEvent[]): CatalystEvent[] =>
  (Array.isArray(events) ? events : [])
    .filter((e): e is CatalystEvent => !!e && typeof e === 'object' && typeof e.date === 'string')
    .slice()
    .sort((a, b) =>
      (Number.isFinite(a.days_until) ? a.days_until : Infinity) -
        (Number.isFinite(b.days_until) ? b.days_until : Infinity) ||
      a.date.localeCompare(b.date)
    )

// 置顶事件 = 最小 days_until（并列取日期更早者）
export const nextEventOf = (events: CatalystEvent[]): CatalystEvent | null => {
  const sorted = sortEvents(events)
  return sorted.length > 0 ? sorted[0] : null
}

// 时间桶分组（1w → 1m → 3m → later 固定顺序；空桶不出现）
export const groupByBucket = (events: CatalystEvent[]): [string, CatalystEvent[]][] => {
  const groups = new Map<string, CatalystEvent[]>()
  for (const ev of sortEvents(events)) {
    const key = (BUCKET_ORDER as readonly string[]).includes(ev.bucket)
      ? ev.bucket
      : 'later'
    const list = groups.get(key) || []
    list.push(ev)
    groups.set(key, list)
  }
  return BUCKET_ORDER
    .filter((b) => groups.has(b))
    .map((b) => [b, groups.get(b) as CatalystEvent[]])
}

/* ── 单标的催化剂卡 ─────────────────────────────────────────────── */

// 事件行：日期 + 类型 chip + 加粗标题 + 一行摘要（CN 纵向 feed 惯例）
const EventRow = ({ event, symbol }: { event: CatalystEvent; symbol: string }) => {
  const chip = eventTypeChip(event.type)
  const detail = detailLineOf(event, symbol)
  return (
    <div className="flex items-start gap-2 py-1.5 border-b border-slate-100 last:border-0 last:pb-0">
      <span className="text-xs text-slate-400 font-mono shrink-0 pt-0.5 tabular-nums">{event.date}</span>
      <span className={cn('px-1.5 py-0.5 rounded text-[11px] font-semibold shrink-0', chip.bg, chip.color)}>
        {chip.label}
      </span>
      <div className="min-w-0">
        <p className="text-sm font-medium text-slate-800 leading-snug">{event.title}</p>
        {detail && <p className="text-xs text-slate-500 mt-0.5">{detail}</p>}
      </div>
    </div>
  )
}

export function CatalystTimeline({ symbol, data }: { symbol: string; data: SymbolCatalysts | null | undefined }) {
  // useState 在渲染门前调用（hooks 顺序不受数据有无影响）
  const [laterOpen, setLaterOpen] = useState(false)
  if (!hasCatalystContent(data)) return null

  const events = sortEvents(data?.events || [])
  const next = nextEventOf(events)
  const groups = groupByBucket(events)
  const surprise = Array.isArray(data?.earnings_surprise) ? data.earnings_surprise : []
  const laterGroup = groups.find(([b]) => b === 'later')
  const feedGroups = groups.filter(([b]) => b !== 'later')

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center justify-between">
          <span className="flex items-center gap-2">
            <CalendarClock className="h-4 w-4 text-slate-500" />
            催化剂时间轴
          </span>
          <Badge variant="outline">{symbol}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* 置顶：下一个催化剂（days_until 突出显示） */}
        {next && (
          <div className="p-3 border border-blue-200 bg-blue-50 rounded-lg">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-medium text-blue-600 mb-1">下一个催化剂</p>
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={cn(
                      'px-1.5 py-0.5 rounded text-[11px] font-semibold',
                      eventTypeChip(next.type).bg,
                      eventTypeChip(next.type).color
                    )}
                  >
                    {eventTypeChip(next.type).label}
                  </span>
                  <span className="text-xs text-slate-500 font-mono tabular-nums">{next.date}</span>
                </div>
                <p className="text-sm font-bold text-slate-900">{next.title}</p>
                {detailLineOf(next, symbol) && (
                  <p className="text-xs text-slate-500 mt-0.5">{detailLineOf(next, symbol)}</p>
                )}
              </div>
              <p className="text-2xl font-bold text-blue-600 shrink-0 tabular-nums" title="距今天数">
                {daysUntilZh(next.days_until)}
              </p>
            </div>
          </div>
        )}

        {/* 分桶纵向 feed（更远默认折叠） */}
        {groups.length > 0 && (
          <div className="space-y-3">
            {feedGroups.map(([bucket, rows]) => (
              <div key={bucket}>
                <p className="text-xs font-medium text-slate-400 mb-1">{bucketZh(bucket)}</p>
                {rows.map((ev, i) => (
                  <EventRow key={`${ev.date}-${i}`} event={ev} symbol={symbol} />
                ))}
              </div>
            ))}
            {laterGroup && (
              <div>
                <button
                  onClick={() => setLaterOpen(!laterOpen)}
                  className="w-full flex items-center justify-between text-xs font-medium text-slate-400 mb-1 hover:text-slate-600"
                  title={laterOpen ? '收起更远的事件' : '展开更远的事件'}
                >
                  <span>
                    {bucketZh(laterGroup[0])} · {laterGroup[1].length} 条
                  </span>
                  {laterOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                </button>
                {laterOpen && laterGroup[1].map((ev, i) => (
                  <EventRow key={`${ev.date}-${i}`} event={ev} symbol={symbol} />
                ))}
              </div>
            )}
          </div>
        )}

        {/* 近四季 EPS 预期差迷你表（正偏差绿、负偏差红） */}
        {surprise.length > 0 && (
          <div>
            <p className="text-xs font-medium text-slate-500 mb-1.5">近四季 EPS 预期差</p>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-slate-400 border-b border-slate-200">
                  <th className="py-1 pr-3 font-normal">日期</th>
                  <th className="py-1 pr-3 font-normal text-right">预期</th>
                  <th className="py-1 pr-3 font-normal text-right">实际</th>
                  <th className="py-1 font-normal text-right">偏差%</th>
                </tr>
              </thead>
              <tbody>
                {surprise.map((row, i) => (
                  <tr key={row?.date ?? i} className="border-b border-slate-100 last:border-0">
                    <td className="py-1 pr-3 text-slate-600 font-mono tabular-nums">{row.date}</td>
                    <td className="py-1 pr-3 text-right text-slate-600 tabular-nums">
                      {formatNumber(row.estimate, 2)}
                    </td>
                    <td className="py-1 pr-3 text-right font-medium text-slate-700 tabular-nums">
                      {formatNumber(row.actual, 2)}
                    </td>
                    <td
                      className={cn(
                        'py-1 text-right font-semibold tabular-nums',
                        row.surprise_pct >= 0 ? 'text-green-600' : 'text-red-600'
                      )}
                    >
                      {formatSignedPctPoint(row.surprise_pct)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

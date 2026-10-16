'use client'

import type { ReactNode } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { formatNumber, formatPercent, formatSignedPercent, formatCurrency, currencyForSymbol } from '@/lib/format'
import type { Consensus, OptionImplied, Trend, TrendQoQMetric, TrendYoYMetric } from './types'

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

/* 期权隐含情绪标注块 —— pipeline / ReAct 两个报告视图共用同一渲染，保证视觉
 * 一致。纯标注：只读 wire 上的 option_implied 块；全空（无 regime 亦无任何
 * 可显示行）时整块不渲染，绝不伪造「中性」。 */

const OPTION_REGIME_STYLE: Record<string, { bg: string; color: string }> = {
  恐慌: { bg: 'bg-red-100', color: 'text-red-700' },
  自满: { bg: 'bg-sky-100', color: 'text-sky-700' },
  中性: { bg: 'bg-slate-100', color: 'text-slate-600' },
}

// regime → 徽章样式/文案；status 非 ok 或 regime 缺席 → amber「数据不足」
// （诚实的缺席，比照 build_option_implied 的 insufficient_data 约定）
export const optionImpliedBadge = (block: OptionImplied): { bg: string; color: string; label: string } => {
  if (block.status === 'ok' && block.regime != null) {
    return { ...(OPTION_REGIME_STYLE[block.regime] || { bg: 'bg-slate-100', color: 'text-slate-600' }), label: block.regime }
  }
  return { bg: 'bg-amber-100', color: 'text-amber-700', label: '数据不足' }
}

// 整块渲染门：任一可显示内容存在才渲染（regime 或任一指标行）
export const hasOptionImpliedContent = (block: OptionImplied): boolean =>
  (block.status === 'ok' && block.regime != null) ||
  block.qvix?.current != null ||
  block.iv?.atm_iv_near != null ||
  block.iv?.term_structure != null ||
  block.iv?.skew_25d != null ||
  block.pcr?.market_pcr != null

export const OptionImpliedBlock = ({ block }: { block: OptionImplied }) => {
  const { qvix, iv, pcr } = block
  if (!hasOptionImpliedContent(block)) return null
  const badge = optionImpliedBadge(block)
  const inverted = iv?.term_structure != null && iv.term_structure < 0
  return (
    <div className="p-3 border border-slate-200 rounded-lg space-y-1 text-xs">
      <div className="flex items-center justify-between">
        <span className="text-slate-500">期权隐含情绪（CN 场内期权）</span>
        <span className={cn('px-2 py-0.5 rounded text-xs font-semibold', badge.bg, badge.color)}>{badge.label}</span>
      </div>
      {qvix?.current != null && (
        <div className="flex justify-between">
          <span className="text-slate-500">QVIX（中国波指）</span>
          <span className="font-medium">
            {formatNumber(qvix.current, 2)}
            {qvix.percentile_1y != null && (
              <span className="ml-1 font-normal text-slate-400">· 1年分位 {formatPercent(qvix.percentile_1y, 0)}</span>
            )}
            {qvix.as_of && <span className="ml-1 font-normal text-slate-400">截至 {qvix.as_of}</span>}
          </span>
        </div>
      )}
      {iv?.atm_iv_near != null && (
        <div className="flex justify-between">
          <span className="text-slate-500">ATM 隐含波动率</span>
          <span className="font-medium">
            {formatPercent(iv.atm_iv_near)}（近月）
            {iv.atm_iv_next != null && (
              <span className="ml-1 font-normal text-slate-400">次月 {formatPercent(iv.atm_iv_next)}</span>
            )}
          </span>
        </div>
      )}
      {iv?.term_structure != null && (
        <div className="flex justify-between">
          <span className="text-slate-500">期限结构（近月−次月）</span>
          <span className={cn('font-medium', inverted ? 'text-amber-600' : 'text-slate-600')}>
            {formatSignedPercent(iv.term_structure)}
          </span>
        </div>
      )}
      {inverted && <p className="text-amber-600">⚠ 近月高于次月——期限倒挂（近端恐慌）</p>}
      {iv?.skew_25d != null && (
        <div className="flex justify-between">
          <span className="text-slate-500">25Δ 偏度（正 = 下行保护贵）</span>
          <span className="font-medium">{formatSignedPercent(iv.skew_25d)}</span>
        </div>
      )}
      {pcr?.market_pcr != null && (
        <div className="flex justify-between">
          <span className="text-slate-500">市场 PCR（认沽/认购）</span>
          <span className="font-medium">{formatNumber(pcr.market_pcr, 2)}</span>
        </div>
      )}
      <p className="text-slate-400">{iv?.n_filtered ? `${iv.n_filtered} 份筛选后合约 · ` : ''}纯标注，不影响评分</p>
    </div>
  )
}

/* CN 分析师一致预期标注块 —— pipeline / ReAct 两个报告视图共用（镜像
 * OptionImpliedBlock 的定位）。纯标注：只读 wire 上的 fundamental
 * by_symbol[symbol].consensus 块（THS EPS 预测 / 新浪评级，迭代 163）；
 * 全部子块缺席时整块不渲染。US-only run 无此键，渲染面零扰动。 */

// status → 徽章样式/文案；ratings-only（insufficient_data）→ amber「数据不足」
// ——评级计数仍是真实可显示数据，照常渲染在徽章下方
export const consensusBadge = (block: Consensus): { bg: string; color: string; label: string } => {
  if (block.status === 'ok') return { bg: 'bg-slate-100', color: 'text-slate-600', label: '机构预期' }
  return { bg: 'bg-amber-100', color: 'text-amber-700', label: '数据不足' }
}

// 整块渲染门：任一子块存在才渲染（降级 run 整键缺席，由调用方守卫兜底）
export const hasConsensusContent = (block: Consensus): boolean =>
  block.eps_forecast != null || block.target_price != null || block.ratings != null

export const ConsensusBlock = ({ symbol, consensus: c }: { symbol: string; consensus: Consensus }) => {
  if (!hasConsensusContent(c)) return null
  const badge = consensusBadge(c)
  const currency = currencyForSymbol(symbol)
  // Market suffix mirrors the backend dispatch: 6-digit symbols ride the CN
  // price seam, everything else the US ratings-only seam (Finnhub) — the
  // header must not claim CN coverage for an AAPL ratings block.
  const marketSuffix = /^\d{6}$/.test(symbol) ? 'CN' : 'US'
  const eps = c.eps_forecast
  const tp = c.target_price
  const ratings = c.ratings
  return (
    <div className="p-3 border border-slate-200 rounded-lg space-y-1 text-xs">
      <div className="flex items-center justify-between">
        <span className="text-slate-500">{`分析师一致预期（${marketSuffix}）`}</span>
        <span className={cn('px-2 py-0.5 rounded text-xs font-semibold', badge.bg, badge.color)}>{badge.label}</span>
      </div>
      {eps != null && (
        <div className="flex justify-between">
          <span className="text-slate-500">{`EPS 预测（${eps.year1} 年）`}</span>
          <span className="font-medium">
            {formatCurrency(eps.eps_mean, currency)}
            {eps.org_count != null && (
              <span className="ml-1 font-normal text-slate-400">{`· ${eps.org_count} 家机构`}</span>
            )}
            {eps.industry_avg != null && (
              <span className="ml-1 font-normal text-slate-400">{`· 行业 ${formatCurrency(eps.industry_avg, currency)}`}</span>
            )}
          </span>
        </div>
      )}
      {eps?.year2 != null && eps.eps_mean_year2 != null && (
        <div className="flex justify-between">
          <span className="text-slate-500">{`EPS 预测（${eps.year2} 年）`}</span>
          <span className="font-medium">
            {formatCurrency(eps.eps_mean_year2, currency)}
            {eps.implied_growth != null && (
              <span className={cn('ml-1 font-normal', eps.implied_growth >= 0 ? 'text-green-600' : 'text-red-600')}>
                {`同比 ${formatSignedPercent(eps.implied_growth)}`}
              </span>
            )}
          </span>
        </div>
      )}
      {tp != null && (
        <div className="flex justify-between">
          <span className="text-slate-500">{`目标价（${tp.count} 家 · 近${tp.window_days}天）`}</span>
          <span className="font-medium">
            {formatCurrency(tp.mean, currency)}
            <span className="ml-1 font-normal text-slate-400">{`· 中位 ${formatCurrency(tp.median, currency)}`}</span>
            {tp.implied_upside != null && (
              <span className={cn('ml-1 font-normal', tp.implied_upside >= 0 ? 'text-green-600' : 'text-red-600')}>
                {`· ${formatSignedPercent(tp.implied_upside)}`}
              </span>
            )}
          </span>
        </div>
      )}
      {ratings != null && (
        <div className="flex justify-between">
          <span className="text-slate-500">机构评级</span>
          <span className="font-medium">
            {['买入', '增持', '中性', '减持', '卖出']
              .filter((l) => (ratings.counts[l] ?? 0) > 0)
              .map((l) => `${l} ${ratings.counts[l] ?? 0}`)
              .join(' · ')}
            <span className="ml-1 font-normal text-slate-400">{`· 主导 ${ratings.dominant}`}</span>
          </span>
        </div>
      )}
      <p className="text-slate-400">
        {ratings ? `${ratings.total} 条评级 · ` : ''}纯标注，不影响评分
      </p>
    </div>
  )
}

/* 基本面趋势标注块 —— pipeline / ReAct 两个报告视图共用（镜像
 * ConsensusBlock 的定位）。纯标注：只读 wire 上的 fundamental
 * by_symbol[symbol].trend 块（迭代 191：CN indicators_history 同期同比 /
 * US-HK statements_quarterly 季度环比）；metrics 空或缺席时整块不渲染。
 * 未知指标键渲染原始键名（数据驱动兜底，后端加指标零前端改动）。 */

const TREND_YOY_LABELS: Record<string, string> = {
  roe: 'ROE',
  profit_margin: '净利率',
  gross_margin: '毛利率',
  revenue_growth: '营收增速',
  earnings_growth: '盈利增速',
}

const TREND_QOQ_LABELS: Record<string, string> = {
  revenue: '营收',
  net_income: '净利润',
}

// direction → 颜色/箭头/文案（同比环比共用；flat 用 ± 而非 +，
// 「零变化」不是「正变化」）
export const trendDirectionStyle = (direction: string): { color: string; arrow: string } => {
  if (direction === 'improving') return { color: 'text-green-600', arrow: '↑' }
  if (direction === 'deteriorating') return { color: 'text-red-600', arrow: '↓' }
  return { color: 'text-slate-400', arrow: '→' }
}

// 整块渲染门：至少一个指标在场（降级 run 整键缺席，由调用方守卫兜底）
export const hasTrendContent = (trend: Trend | null | undefined): boolean =>
  !!trend && !!trend.metrics && Object.keys(trend.metrics).length > 0

// symbol prop 预留（镜像 ConsensusBlock 签名便于调用方统一）——CN 比率与
// US 报表原值都不需要币种路由，故不解构
export const TrendBlock = ({ trend }: { symbol: string; trend: Trend }) => {
  if (!hasTrendContent(trend)) return null
  const isYoy = trend.basis === 'same_period_prior_year'
  const header = isYoy
    ? `基本面趋势（同比 · 截至 ${trend.as_of ?? '—'}）`
    : '基本面趋势（环比 · 近4季）'
  const footer = isYoy ? '同期上年对比 · 纯标注，不影响评分' : '季度环比 · 纯标注，不影响评分'
  return (
    <div className="p-3 border border-slate-200 rounded-lg space-y-1 text-xs">
      <div className="flex items-center justify-between">
        <span className="text-slate-500">{header}</span>
      </div>
      {Object.entries(trend.metrics).map(([key, metric]) => {
        const style = trendDirectionStyle(metric.direction)
        if (isYoy) {
          const m = metric as TrendYoYMetric
          return (
            <div key={key} className="flex justify-between">
              <span className="text-slate-500">{TREND_YOY_LABELS[key] ?? key}</span>
              <span className="font-medium">
                {formatPercent(m.value)}
                <span className="ml-1 font-normal text-slate-400">{`上年 ${formatPercent(m.year_ago)}`}</span>
                <span className={cn('ml-1 font-normal', style.color)}>
                  {metric.direction === 'flat'
                    ? `${style.arrow} ±${formatPercent(Math.abs(m.delta))}`
                    : `${style.arrow} ${formatSignedPercent(m.delta)}`}
                </span>
              </span>
            </div>
          )
        }
        const m = metric as TrendQoQMetric
        return (
          <div key={key} className="flex justify-between">
            <span className="text-slate-500">{TREND_QOQ_LABELS[key] ?? key}</span>
            <span className="font-medium">
              {m.quarters.map((q) => formatNumber(q.value, 1)).join(' → ')}
              <span className={cn('ml-1 font-normal', style.color)}>
                {`${style.arrow} ${m.latest_qoq_delta >= 0 ? '+' : ''}${formatNumber(m.latest_qoq_delta, 1)}`}
              </span>
            </span>
          </div>
        )
      })}
      <p className="text-slate-400">{footer}</p>
    </div>
  )
}

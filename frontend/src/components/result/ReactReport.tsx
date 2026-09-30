'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'
import {
  formatNumber, formatPercent, formatAdv, formatCurrency,
  currencyForSymbol, formatMarketCap, sparkColor,
} from '@/lib/format'
import { ResponsiveContainer, AreaChart, Area, YAxis } from 'recharts'
import {
  actionZh, actionStyle, trendZh, trendColor, riskZh, riskStyle,
  sentimentZh, scoreOf, SectionCard, OptionImpliedBlock, ConsensusBlock,
} from './report-shared'
import { CatalystTimeline } from './CatalystTimeline'
import type { SymbolCatalysts } from './types'
import { BarChart3, Brain, Database, Hash, Newspaper, PieChart, Shield } from 'lucide-react'

// ReAct 结构化报告组件 —— 把 answer(JSON)渲染成人类可读的投资报告
export function ReactReport({ answer, report: structuredReport }: {
  answer: string
  report: Record<string, any> | null
}) {
  const [activeSymbol, setActiveSymbol] = useState<string>('all')
  const [openEvidence, setOpenEvidence] = useState<string | null>(null)
  let report: any = structuredReport
  if ((!report || typeof report !== 'object') && typeof answer === 'string' && answer.trim()) {
    try {
      report = JSON.parse(answer)
    } catch {
      report = null
    }
  }

  if (!report || typeof report !== 'object') {
    return (
      <div className="prose prose-slate max-w-none">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{answer || '暂无报告内容'}</ReactMarkdown>
      </div>
    )
  }

  const sections = report.sections || {}
  const overview = sections.overview || {}
  const technical = sections.technical_analysis || {}
  const fundamental = sections.fundamental_analysis || {}
  const sentiment = sections.sentiment_analysis || {}
  const risk = sections.risk_analysis || {}
  const recommendations = sections.recommendations || {}
  const synthesis = sections.research_synthesis || null
  const evidenceIndex = sections.evidence_index || {}
  const catalysts = sections.catalysts || {}

  const filterEntries = (entries: [string, any][]): [string, any][] =>
    activeSymbol === 'all' ? entries : entries.filter(([s]) => s === activeSymbol)

  const recEntries = recommendations.by_symbol ? Object.entries(recommendations.by_symbol) : []
  const overviewEntries = overview.market_summary ? Object.entries(overview.market_summary) : []
  const hasTech = technical.by_symbol && Object.keys(technical.by_symbol).length > 0
  const hasFund = fundamental.by_symbol && Object.keys(fundamental.by_symbol).length > 0
  const hasSent = sentiment.by_symbol && Object.keys(sentiment.by_symbol).length > 0
  const hasRisk = risk.by_symbol && Object.keys(risk.by_symbol).length > 0

  const symbolUniverse: string[] = Array.from(
    new Set([
      ...overviewEntries.map(([s]) => s),
      ...Object.keys(technical.by_symbol || {}),
      ...Object.keys(fundamental.by_symbol || {}),
      ...(synthesis?.by_symbol ? Object.keys(synthesis.by_symbol) : []),
      ...Object.keys(catalysts.by_symbol || {}),
    ])
  )

  return (
    <div className="space-y-6">
      {/* 标题 + 执行摘要 */}
      {report.title && (
        <div>
          <h2 className="text-2xl font-bold text-slate-900 mb-3">{report.title}</h2>
          {report.executive_summary && (
            <div className="p-4 bg-blue-50 border border-blue-100 rounded-lg">
              <p className="text-sm text-slate-800 leading-relaxed">{report.executive_summary}</p>
            </div>
          )}
        </div>
      )}

      {/* 标的切换 */}
      {symbolUniverse.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {['all', ...symbolUniverse].map(sym => (
            <button
              key={sym}
              onClick={() => setActiveSymbol(sym)}
              className={cn(
                'px-3 py-1 rounded-full text-sm font-medium border transition-colors',
                activeSymbol === sym
                  ? 'bg-slate-900 text-white border-slate-900'
                  : 'bg-white text-slate-600 border-slate-200 hover:border-slate-400'
              )}
            >
              {sym === 'all' ? '全部标的' : sym}
            </button>
          ))}
        </div>
      )}

      {/* 投资建议卡片(最突出) */}
      {filterEntries(recEntries).length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {filterEntries(recEntries).map(([sym, rec]: [string, any]) => {
            const st = actionStyle(rec.action)
            const composite = scoreOf(rec.composite_score)
            const conf = typeof rec.confidence === 'number' ? rec.confidence : 0.5
            return (
              <Card key={sym} className={cn('ring-1', st.ring)}>
                <CardContent className="p-5">
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <p className="text-xs text-slate-500">投资建议 · {sym}</p>
                      <p className="text-2xl font-bold mt-0.5">{actionZh(rec.action)}</p>
                    </div>
                    <div className={cn('px-4 py-2 rounded-full', st.bg)}>
                      <span className={cn('text-sm font-semibold', st.color)}>{(conf * 100).toFixed(0)}% 置信</span>
                    </div>
                  </div>
                  {composite !== null && (
                    <div className="mb-2">
                      <div className="flex justify-between text-xs text-slate-500 mb-1">
                        <span>综合评分</span>
                        <span className="font-medium text-slate-700">{composite.toFixed(0)} / 100</span>
                      </div>
                      <Progress value={composite} className="h-2" />
                    </div>
                  )}
                  {(rec.entry != null || rec.stop_loss != null || rec.take_profit != null || rec.position_size != null) && (
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 mt-3 p-2.5 bg-slate-50 rounded-lg text-xs">
                      {rec.entry != null && (
                        <div className="flex justify-between"><span className="text-slate-500">建议买入区</span><span className="font-medium">{formatCurrency(rec.entry, currencyForSymbol(sym))}</span></div>
                      )}
                      {rec.stop_loss != null && (
                        <div className="flex justify-between"><span className="text-slate-500">止损价</span><span className="font-medium text-red-600">{formatCurrency(rec.stop_loss, currencyForSymbol(sym))}</span></div>
                      )}
                      {rec.take_profit != null && (
                        <div className="flex justify-between"><span className="text-slate-500">止盈价</span><span className="font-medium text-green-600">{formatCurrency(rec.take_profit, currencyForSymbol(sym))}</span></div>
                      )}
                      {rec.position_size != null && (
                        <div className="flex justify-between col-span-2"><span className="text-slate-500">建议仓位</span><span className="font-medium">{formatNumber(rec.position_size, 1)}% 的投资组合</span></div>
                      )}
                    </div>
                  )}
                  {rec.warnings?.length > 0 && (
                    <div className="mt-2 p-2 bg-amber-50 border border-amber-100 rounded text-xs text-amber-700 space-y-0.5">
                      {rec.warnings.map((w: string, i: number) => (
                        <p key={i}>⚠ {w}</p>
                      ))}
                    </div>
                  )}
                  {(rec.reasoning || rec.rationale) && (
                    <p className="text-xs text-slate-500 mt-2 leading-relaxed">{rec.reasoning || rec.rationale}</p>
                  )}
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      {/* 组合权重建议（conviction/vol 加权 + 单票上限） */}
      {recommendations.suggested_weights?.weights && Object.keys(recommendations.suggested_weights.weights).length > 0 && (() => {
        const sw = recommendations.suggested_weights
        const entries = Object.entries(sw.weights) as [string, number][]
        return (
          <SectionCard icon={PieChart} title="组合权重建议">
            <div className="space-y-3">
              {entries.map(([sym, w]) => (
                <div key={sym}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="font-medium">{sym}</span>
                    <span className="text-slate-600">{(w * 100).toFixed(1)}%</span>
                  </div>
                  <Progress value={w * 100} className="h-2" />
                </div>
              ))}
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs pt-1 border-t border-slate-100">
                <div className="flex justify-between"><span className="text-slate-500">现金保留</span><span className="font-medium">{formatPercent(sw.cash_reserve)}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">集中度 HHI</span><span className="font-medium">{formatNumber(sw.concentration_hhi, 3)}</span></div>
              </div>
              {sw.excluded?.length > 0 && (
                <p className="text-xs text-slate-400">未纳入：{sw.excluded.join('、')}（非买入类建议或缺少波动率数据）</p>
              )}
              <p className="text-xs text-slate-400">方法：{sw.method === 'conviction_tilted_inverse_volatility' ? '置信度倾斜逆波动率加权，单票上限 ' + formatPercent(sw.max_weight, 0) : sw.method || '-'}</p>
            </div>
          </SectionCard>
        )
      })()}

      {/* 决策综合叙事（LLM · 市场状态感知，纯叙事不改数字） */}
      {report.decision_synthesis?.synthesis && (
        <div className="p-4 border border-indigo-100 bg-indigo-50/50 rounded-lg">
          <p className="text-xs font-medium text-indigo-600 mb-1">
            决策综合{report.decision_synthesis.top_pick ? ` · 综合分居首 ${report.decision_synthesis.top_pick}` : ''}
          </p>
          <p className="text-sm text-slate-700 leading-relaxed whitespace-pre-line">{report.decision_synthesis.synthesis}</p>
        </div>
      )}

      {/* 市场概览 */}
      {filterEntries(overviewEntries).length > 0 && (
        <SectionCard icon={Database} title="市场概览">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {filterEntries(overviewEntries).map(([sym, info]: [string, any]) => (
              <div key={sym} className="p-3 bg-slate-50 rounded-lg">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-medium">{info.company_name || sym}</span>
                  <Badge variant="outline">{sym}</Badge>
                </div>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <p className="text-xs text-slate-500">当前价</p>
                    <p className="font-semibold">{formatCurrency(info.current_price, info.currency || currencyForSymbol(sym))}</p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-500">涨跌幅</p>
                    <p className={cn('font-semibold', (info.change_percent || 0) >= 0 ? 'text-green-600' : 'text-red-600')}>
                      {(info.change_percent || 0) >= 0 ? '+' : ''}{formatNumber(info.change_percent)}%
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-500">行业</p>
                    <p className="font-medium">{info.sector || '-'}</p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-500">市值</p>
                    <p className="font-medium">{formatMarketCap(info.market_cap, info.currency || currencyForSymbol(sym))}</p>
                  </div>
                  {info.earnings?.next_earnings_date != null && (
                    <div>
                      <p className="text-xs text-slate-500">下次财报</p>
                      <p className={cn('font-medium', info.earnings.days_until <= 7 ? 'text-amber-600' : 'text-slate-600')}>
                        {info.earnings.next_earnings_date}
                        <span className="ml-1 font-normal text-slate-400">
                          （{info.earnings.days_until === 0 ? '今天' : `${info.earnings.days_until} 天后`}）
                        </span>
                      </p>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
          {overview.analysis_date && (
            <p className="text-xs text-slate-400 mt-3">分析日期：{overview.analysis_date}</p>
          )}
        </SectionCard>
      )}

      {/* 催化剂时间轴 —— 事件标注（by_symbol 逐标的卡；'all' 时逐卡展示，
       * 选中标的时 filterEntries 只留该标的；旧报告整键缺席 → 零渲染） */}
      {filterEntries(Object.entries(catalysts.by_symbol || {})).map(([sym, c]) => (
        <CatalystTimeline key={sym} symbol={sym} data={c as SymbolCatalysts} />
      ))}

      {/* 技术分析 + 基本面(双栏) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {hasTech && (
          <SectionCard icon={BarChart3} title="技术分析">
            <div className="space-y-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500">整体展望</span>
                <span className={cn('font-semibold', trendColor(technical.overall_outlook))}>{trendZh(technical.overall_outlook)}</span>
              </div>
              {filterEntries(Object.entries(technical.by_symbol)).map(([sym, t]: [string, any]) => {
                const weekly = t.weekly_trend || {}
                const alignment = weekly.alignment?.state
                const crosses = Object.entries(weekly.recent_crosses || {})
                return (
                  <div key={sym} className="p-3 bg-slate-50 rounded-lg space-y-1 text-sm">
                    <div className="flex items-center justify-between mb-1">
                      <p className="font-medium">{sym}</p>
                      {Array.isArray(t.price_spark) && t.price_spark.length > 1 && (() => {
                        const first = t.price_spark[0]
                        const last = t.price_spark[t.price_spark.length - 1]
                        const changePct = ((last - first) / first) * 100
                        return (
                          <span className={cn('text-xs tabular-nums', changePct >= 0 ? 'text-green-600' : 'text-red-600')}>
                            {changePct >= 0 ? '+' : ''}{changePct.toFixed(1)}%
                          </span>
                        )
                      })()}
                    </div>
                    {Array.isArray(t.price_spark) && t.price_spark.length > 1 && (
                      <div className="h-14 -mx-1">
                        <ResponsiveContainer width="100%" height="100%">
                          <AreaChart
                            data={t.price_spark.map((v: number, i: number) => ({ i, v }))}
                            margin={{ top: 4, bottom: 0, left: 0, right: 0 }}
                          >
                            <YAxis hide domain={['dataMin', 'dataMax']} />
                            <Area
                              type="monotone"
                              dataKey="v"
                              stroke={sparkColor(t.trend)}
                              fill={sparkColor(t.trend)}
                              fillOpacity={0.12}
                              strokeWidth={1.5}
                              dot={false}
                              isAnimationActive={false}
                            />
                          </AreaChart>
                        </ResponsiveContainer>
                      </div>
                    )}
                    {t.status ? (
                      <p className="text-xs text-amber-600">
                        ⚠ 行情数据不可用（{t.status === 'insufficient_data' ? '历史数据不足' : '未获取到行情数据'}），未生成技术分析
                      </p>
                    ) : (
                      <>
                        <div className="flex justify-between"><span className="text-slate-500">趋势</span><span className={trendColor(t.trend)}>{trendZh(t.trend)}</span></div>
                        {t.adx != null && (
                          <div className="flex justify-between">
                            <span className="text-slate-500">趋势强度</span>
                            <span className={cn('font-medium', t.trend_strength === 'strong' || t.trend_strength === 'very_strong' ? 'text-green-600' : t.trend_strength === 'developing' ? 'text-amber-600' : 'text-slate-500')}>
                              {t.trend_strength === 'very_strong' ? '极强' : t.trend_strength === 'strong' ? '强势' : t.trend_strength === 'developing' ? '形成中' : '偏弱（区间）'}
                              <span className="ml-1.5 font-normal text-slate-400">ADX {t.adx.toFixed(1)}</span>
                            </span>
                          </div>
                        )}
                        {t.macd != null && (
                          <div className="flex justify-between"><span className="text-slate-500">MACD</span><span className={trendColor(t.macd)}>{trendZh(t.macd)}</span></div>
                        )}
                        <div className="flex justify-between"><span className="text-slate-500">RSI</span><span className={trendColor(t.rsi)}>{trendZh(t.rsi)}</span></div>
                        {(t.support?.s1 != null || t.resistance?.r1 != null) && (
                          <div className="flex justify-between">
                            <span className="text-slate-500">支撑 / 压力</span>
                            <span className="font-medium">
                              <span className="text-green-700">{t.support?.s1 != null ? formatNumber(t.support.s1) : '-'}</span>
                              {' / '}
                              <span className="text-red-700">{t.resistance?.r1 != null ? formatNumber(t.resistance.r1) : '-'}</span>
                            </span>
                          </div>
                        )}
                        {t.freshness?.stale && (
                          <p className="text-xs text-amber-600">⚠ 数据截至 {t.freshness.as_of}（{t.freshness.age_days} 天前，已陈旧）</p>
                        )}
                        <div className="flex justify-between"><span className="text-slate-500">情绪分</span><span className={cn('font-medium', (t.sentiment_score || 0) >= 0 ? 'text-green-600' : 'text-red-600')}>{formatNumber(t.sentiment_score, 0)}</span></div>
                        {alignment && !['insufficient_data', 'unknown'].includes(alignment) && (
                          <div className="flex justify-between">
                            <span className="text-slate-500">周线排列</span>
                            <span className={trendColor(alignment)}>
                              {alignment === 'bullish' ? '多头' : alignment === 'bearish' ? '空头' : '缠绕'}
                              {weekly.alignment.weeks_in_state ? ` · ${weekly.alignment.weeks_in_state} 周` : ''}
                            </span>
                          </div>
                        )}
                        {weekly.status === 'insufficient_data' && (
                          <div className="flex justify-between"><span className="text-slate-500">周线排列</span><span className="text-slate-400">数据不足</span></div>
                        )}
                        {crosses.map(([pair, cross]: [string, any]) => cross?.direction && (
                          <div key={pair} className="flex justify-between">
                            <span className="text-slate-500">交叉 {pair.replace('_', '/')}</span>
                            <span className={cross.direction === 'golden' ? 'text-green-600' : 'text-red-600'}>
                              {cross.direction === 'golden' ? '金叉' : '死叉'}
                              {cross.weeks_since != null ? ` · ${cross.weeks_since} 周前` : ''}
                            </span>
                          </div>
                        ))}
                      </>
                    )}
                  </div>
                )
              })}
            </div>
          </SectionCard>
        )}

        {hasFund && (
          <SectionCard icon={PieChart} title="基本面分析">
            <div className="space-y-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500">整体评级</span>
                <span className="font-semibold">{trendZh(fundamental.overall_rating)}</span>
              </div>
              {filterEntries(Object.entries(fundamental.by_symbol)).map(([sym, f]: [string, any]) => {
                const score = scoreOf(f.overall_score)
                const scenarios = f.valuation_scenarios?.scenarios || {}
                const flags: any[] = f.quality?.red_flags || []
                return (
                  <div key={sym} className="p-3 bg-slate-50 rounded-lg space-y-2 text-sm">
                    <p className="font-medium">{sym}</p>
                    {score !== null && (
                      <div>
                        <div className="flex justify-between mb-1"><span className="text-slate-500">综合评分</span><span className="font-medium">{formatNumber(score, 0)} / 100</span></div>
                        <Progress value={score} className="h-2" />
                      </div>
                    )}
                    <div className="flex justify-between"><span className="text-slate-500">建议</span><span className="font-medium">{actionZh(f.recommendation)}</span></div>
                    {f.valuation_scenarios?.status === 'available' && (
                      <div>
                        <p className="text-xs text-slate-500 mb-1">估值情景（假设区间，非目标价）</p>
                        <div className="grid grid-cols-3 gap-2">
                          {(['bear', 'base', 'bull'] as const).map(sc => {
                            const block = scenarios[sc] || {}
                            const first = Object.values(block)[0] as any
                            return (
                              <div key={sc} className="p-2 bg-white rounded border border-slate-200 text-center">
                                <p className="text-xs text-slate-400">
                                  {sc === 'bear' ? '悲观' : sc === 'base' ? '基准' : '乐观'}
                                </p>
                                <p className={cn('text-sm font-semibold', sc === 'bear' ? 'text-red-600' : sc === 'bull' ? 'text-green-600' : 'text-slate-700')}>
                                  {first?.value != null ? formatCurrency(first.value, currencyForSymbol(sym)) : '-'}
                                </p>
                                {first?.upside_pct != null && (
                                  <p className={cn('text-xs', first.upside_pct >= 0 ? 'text-green-600' : 'text-red-600')}>
                                    {first.upside_pct >= 0 ? '+' : ''}{formatNumber(first.upside_pct, 1)}%
                                  </p>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}
                    {f.consensus && <ConsensusBlock symbol={sym} consensus={f.consensus} />}
                    {flags.length > 0 && (
                      <div className="space-y-1">
                        {flags.map((flag, i) => (
                          <p key={i} className={cn('text-xs leading-relaxed', flag.severity === 'critical' ? 'text-red-600 font-medium' : 'text-amber-600')}>
                            ⚠ {flag.detail || flag.code}
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </SectionCard>
        )}
      </div>

      {/* 情绪 + 风险(双栏) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {hasSent && (
          <SectionCard icon={Newspaper} title="情绪分析">
            <div className="space-y-3">
              {sentiment.overall && (
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-500">整体情绪</span>
                  <span className="font-semibold">{sentimentZh(sentiment.overall.sentiment)}（{formatNumber(sentiment.overall.score, 0)}）</span>
                </div>
              )}
              {filterEntries(Object.entries(sentiment.by_symbol)).map(([sym, s]: [string, any]) => (
                <div key={sym} className="p-3 bg-slate-50 rounded-lg space-y-1 text-sm">
                  <p className="font-medium mb-1">{sym}</p>
                  <div className="flex justify-between"><span className="text-slate-500">情绪</span><span className="font-medium">{sentimentZh(s.sentiment)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">得分</span><span className={cn('font-medium', (s.score || 0) >= 0 ? 'text-green-600' : 'text-red-600')}>{formatNumber(s.score, 0)}</span></div>
                  {s.trend && s.trend !== 'no_data' && (
                    <div className="flex justify-between">
                      <span className="text-slate-500">趋势</span>
                      <span className={cn('font-medium', s.trend === 'improving' ? 'text-green-600' : s.trend === 'deteriorating' ? 'text-red-600' : 'text-slate-500')}>
                        {s.trend === 'improving' ? '好转' : s.trend === 'deteriorating' ? '恶化' : '平稳'}
                      </span>
                    </div>
                  )}
                  {s.article_count != null && s.article_count > 0 && (
                    <div className="flex justify-between"><span className="text-slate-500">样本</span><span className="text-slate-600">{s.article_count} 篇报道</span></div>
                  )}
                </div>
              ))}
            </div>
          </SectionCard>
        )}

        {hasRisk && (
          <SectionCard icon={Shield} title="风险评估">
            <div className="space-y-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500">整体风险</span>
                {(() => { const rs = riskStyle(risk.overall_risk); return <span className={cn('px-2 py-0.5 rounded text-xs font-semibold', rs.bg, rs.color)}>{riskZh(risk.overall_risk)}</span> })()}
              </div>
              {filterEntries(Object.entries(risk.by_symbol)).map(([sym, r]: [string, any]) => {
                const rs = riskStyle(r.risk_level)
                const rscore = scoreOf(r.risk_score)
                const hasMetrics = r.beta != null || r.volatility != null || r.var_95 != null || r.max_drawdown != null
                return (
                  <div key={sym} className="p-3 bg-slate-50 rounded-lg space-y-2 text-sm">
                    <div className="flex items-center justify-between">
                      <p className="font-medium">{sym}</p>
                      <span className={cn('px-2 py-0.5 rounded text-xs font-semibold', rs.bg, rs.color)}>{riskZh(r.risk_level)}</span>
                    </div>
                    {rscore !== null && (
                      <div>
                        <div className="flex justify-between mb-1"><span className="text-slate-500">风险分</span><span className="font-medium">{formatNumber(rscore, 0)} / 100</span></div>
                        <Progress value={rscore} className="h-2" />
                      </div>
                    )}
                    {hasMetrics && (
                      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                        {r.beta != null && (
                          <div className="flex justify-between"><span className="text-slate-500">β（大盘）</span><span className="font-medium">{formatNumber(r.beta, 2)}{r.beta_ci_95_low != null && r.beta_ci_95_high != null && <span className="ml-1 font-normal text-slate-400">CI {formatNumber(r.beta_ci_95_low, 2)}–{formatNumber(r.beta_ci_95_high, 2)}</span>}</span></div>
                        )}
                        {r.volatility != null && (
                          <div className="flex justify-between"><span className="text-slate-500">年化波动率</span><span className="font-medium">{formatPercent(r.volatility)}</span></div>
                        )}
                        {r.var_95 != null && (
                          <div className="flex justify-between"><span className="text-slate-500">VaR 95%（日）</span><span className="font-medium text-red-600">{formatPercent(r.var_95)}</span></div>
                        )}
                        {r.max_drawdown != null && (
                          <div className="flex justify-between"><span className="text-slate-500">最大回撤</span><span className="font-medium">{formatPercent(r.max_drawdown)}</span></div>
                        )}
                        {r.alpha_annualized != null && (
                          <div className="flex justify-between"><span className="text-slate-500">年化 α</span><span className={cn('font-medium', r.alpha_annualized >= 0 ? 'text-green-600' : 'text-red-600')}>{formatPercent(r.alpha_annualized)}{r.alpha_ci_95_low != null && r.alpha_ci_95_high != null && <span className="ml-1 font-normal text-slate-400">CI {formatPercent(r.alpha_ci_95_low)}–{formatPercent(r.alpha_ci_95_high)}</span>}</span></div>
                        )}
                      </div>
                    )}
                    {r.liquidity?.status === 'available' && (
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-slate-500">流动性（20日均成交额）</span>
                        <span className={cn('font-medium', r.liquidity.level === 'thin' ? 'text-amber-600' : 'text-green-600')}>
                          {r.liquidity.level === 'thin' ? '偏薄' : '充足'} · {formatAdv(r.liquidity.adv_20d, r.liquidity.currency)} {r.liquidity.currency}
                        </span>
                      </div>
                    )}
                    {r.sector_relative?.status === 'available' && (
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-slate-500">行业相对（{r.sector_relative.benchmark_ticker}）</span>
                        <span className="font-medium">β {formatNumber(r.sector_relative.beta_sector, 2)} · R² {formatNumber(r.sector_relative.r_squared_sector, 2)}</span>
                      </div>
                    )}
                    {r.warnings?.length > 0 && (
                      <div className="p-2 bg-amber-50 border border-amber-100 rounded text-xs text-amber-700 space-y-0.5">
                        {r.warnings.map((w: string, i: number) => (
                          <p key={i}>⚠ {w}</p>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
              {risk.portfolio_risk?.correlations?.status === 'available' && (
                <div className="p-3 border border-slate-200 rounded-lg space-y-1 text-xs">
                  <div className="flex justify-between"><span className="text-slate-500">组合平均两两相关</span><span className="font-medium">{formatNumber(risk.portfolio_risk.avg_pairwise_correlation, 2)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">分散化评分</span><span className="font-medium">{formatNumber(risk.portfolio_risk.diversification_score, 0)} / 100</span></div>
                  <p className="text-slate-400">
                    {risk.portfolio_risk.correlations.pairs?.length || 0} 对相关系数 · {risk.portfolio_risk.correlations.aligned_days ?? '-'} 个交易日对齐
                  </p>
                </div>
              )}
              {risk.market_regime?.status === 'ok' && (() => {
                const reg = risk.market_regime
                const trendZh: Record<string, string> = { bull: '牛市', bear: '熊市', neutral: '震荡' }
                const trendColor: Record<string, string> = { bull: 'text-green-600', bear: 'text-red-600', neutral: 'text-slate-600' }
                const volZh: Record<string, string> = { elevated: '高波动', calm: '平静', normal: '正常' }
                const volColor: Record<string, string> = { elevated: 'text-amber-600', calm: 'text-sky-600', normal: 'text-slate-600' }
                return (
                  <div className="p-3 border border-slate-200 rounded-lg space-y-1 text-xs">
                    {reg.trend != null && (
                      <div className="flex justify-between">
                        <span className="text-slate-500">市场状态（基准 vs SMA200）</span>
                        <span className="font-medium">
                          <span className={trendColor[reg.trend] || 'text-slate-600'}>{trendZh[reg.trend] || reg.trend}</span>
                          {reg.price_vs_sma200 != null && <span className="ml-1 font-normal text-slate-400">{formatPercent(reg.price_vs_sma200)}</span>}
                        </span>
                      </div>
                    )}
                    {reg.volatility_regime != null && (
                      <div className="flex justify-between">
                        <span className="text-slate-500">波动率状态（20日 vs 全窗）</span>
                        <span className="font-medium">
                          <span className={volColor[reg.volatility_regime] || 'text-slate-600'}>{volZh[reg.volatility_regime] || reg.volatility_regime}</span>
                          {reg.vol_ratio_20d_vs_full != null && <span className="ml-1 font-normal text-slate-400">×{formatNumber(reg.vol_ratio_20d_vs_full, 2)}</span>}
                        </span>
                      </div>
                    )}
                    {reg.drawdown_from_52w_high != null && (
                      <div className="flex justify-between"><span className="text-slate-500">距 52 周高点</span><span className={cn('font-medium', reg.drawdown_from_52w_high <= -0.1 ? 'text-red-600' : 'text-slate-600')}>{formatPercent(reg.drawdown_from_52w_high)}</span></div>
                    )}
                    <p className="text-slate-400">基于 {reg.bars ?? '-'} 根基准 K 线 · 纯标注，不影响评分</p>
                  </div>
                )
              })()}
              {risk.option_implied && <OptionImpliedBlock block={risk.option_implied} />}
            </div>
          </SectionCard>
        )}
      </div>

      {/* 研究综合：多空质询 · 证据审计 · 风险委员会 */}
      {synthesis?.by_symbol && Object.keys(synthesis.by_symbol).length > 0 && (
        <SectionCard icon={Brain} title="研究综合（多空质询 · 证据审计 · 风险委员会）">
          <div className="space-y-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-500">证据审计判定</span>
              {(() => {
                const v = synthesis.audit_verdict || 'pass'
                const style = v === 'blocked'
                  ? { bg: 'bg-red-100', color: 'text-red-700', label: '已阻断' }
                  : v === 'warnings'
                    ? { bg: 'bg-amber-100', color: 'text-amber-700', label: '有警告' }
                    : { bg: 'bg-green-100', color: 'text-green-700', label: '通过' }
                return <span className={cn('px-2 py-0.5 rounded text-xs font-semibold', style.bg, style.color)}>{style.label}</span>
              })()}
            </div>
            {synthesis.audit_stale?.length > 0 && (
              <p className="text-xs text-red-600">⚠ 数据陈旧：{synthesis.audit_stale.map((s: any) => s.symbol).join('、')}</p>
            )}
            {synthesis.audit_conflicts?.length > 0 && (
              <p className="text-xs text-amber-600">⚠ 证据冲突：{synthesis.audit_conflicts.map((c: any) => c.detail).join('；')}</p>
            )}
            {filterEntries(Object.entries(synthesis.by_symbol)).map(([sym, entry]: [string, any]) => {
              const verdict = entry.committee_verdict || 'watch'
              const vStyle = verdict === 'approve'
                ? { bg: 'bg-green-100', color: 'text-green-700', label: '委员会批准' }
                : verdict === 'limit'
                  ? { bg: 'bg-amber-100', color: 'text-amber-700', label: '委员会限制' }
                  : verdict === 'veto'
                    ? { bg: 'bg-red-100', color: 'text-red-700', label: '委员会否决' }
                    : { bg: 'bg-slate-100', color: 'text-slate-600', label: '仅观察' }
              return (
                <div key={sym} className="p-3 bg-slate-50 rounded-lg space-y-2 text-sm">
                  <div className="flex items-center justify-between">
                    <p className="font-medium">{sym}</p>
                    <span className={cn('px-2 py-0.5 rounded text-xs font-semibold', vStyle.bg, vStyle.color)}>{vStyle.label}</span>
                  </div>
                  {(entry.bull_points?.length > 0 || entry.thesis) && (
                    <div>
                      <p className="text-xs text-green-700 font-medium">多方论据</p>
                      <ul className="mt-1 space-y-1">
                        {(entry.bull_points?.length > 0
                          ? entry.bull_points
                          : [{ claim: entry.thesis, strength: undefined }]
                        ).map((p: any, i: number) => (
                          <li key={i} className="flex items-start gap-2 text-xs text-slate-600 leading-relaxed">
                            <span className="text-green-500 mt-0.5">▲</span>
                            <span className="flex-1">{p.claim}</span>
                            {typeof p.strength === 'number' && (
                              <span className="w-8 h-1 rounded bg-slate-200 shrink-0 mt-1.5 overflow-hidden">
                                <span
                                  className="block h-full rounded bg-green-500"
                                  style={{ width: `${Math.min(100, p.strength)}%` }}
                                />
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {entry.narrative?.bull_narrative && (
                    <div>
                      <p className="text-xs text-green-700 font-medium">多方叙述</p>
                      <p className="text-xs text-slate-600 leading-relaxed">{entry.narrative.bull_narrative}</p>
                    </div>
                  )}
                  {entry.narrative?.bear_narrative && (
                    <div>
                      <p className="text-xs text-red-700 font-medium">空方叙述</p>
                      <p className="text-xs text-slate-600 leading-relaxed">{entry.narrative.bear_narrative}</p>
                    </div>
                  )}
                  {entry.narrative?.pm_comment && (
                    <div>
                      <p className="text-xs text-slate-500 font-medium">组合经理点评</p>
                      <p className="text-xs text-slate-600 leading-relaxed">{entry.narrative.pm_comment}</p>
                    </div>
                  )}
                  {(entry.bear_points?.length > 0 || entry.strongest_counter) && (
                    <div>
                      <p className="text-xs text-red-700 font-medium">空方论据</p>
                      <ul className="mt-1 space-y-1">
                        {(entry.bear_points?.length > 0
                          ? entry.bear_points
                          : [{ claim: entry.strongest_counter, strength: undefined }]
                        ).map((p: any, i: number) => (
                          <li key={i} className="flex items-start gap-2 text-xs text-slate-600 leading-relaxed">
                            <span className="text-red-500 mt-0.5">▼</span>
                            <span className="flex-1">{p.claim}</span>
                            {typeof p.strength === 'number' && (
                              <span className="w-8 h-1 rounded bg-slate-200 shrink-0 mt-1.5 overflow-hidden">
                                <span
                                  className="block h-full rounded bg-red-500"
                                  style={{ width: `${Math.min(100, p.strength)}%` }}
                                />
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {entry.invalidation && (
                    <div>
                      <p className="text-xs text-slate-500 font-medium">失效条件</p>
                      <p className="text-xs text-slate-600 leading-relaxed">{entry.invalidation}</p>
                    </div>
                  )}
                  {entry.pm && (
                    <div className="p-2 bg-blue-50 rounded border border-blue-100">
                      <p className="text-xs text-blue-700 font-medium mb-1">
                        组合经理结论 · {entry.pm.horizon || '期限未声明'}
                        <span className="ml-2 text-slate-400">({entry.pm.committee_verdict})</span>
                      </p>
                      <p className="text-xs text-slate-700 leading-relaxed">{entry.pm.thesis}</p>
                      {entry.pm.conditions?.length > 0 && (
                        <ul className="text-xs text-slate-500 list-disc pl-4 mt-1 space-y-0.5">
                          {entry.pm.conditions.map((cond: string, i: number) => <li key={i}>{cond}</li>)}
                        </ul>
                      )}
                      {entry.pm.invalidation && (
                        <p className="text-xs text-slate-500 mt-1">失效即认错：{entry.pm.invalidation}</p>
                      )}
                    </div>
                  )}
                  {entry.analysts && (
                    <div className="space-y-1">
                      {Object.entries(entry.analysts).map(([role, view]: [string, any]) => (
                        <div key={role} className="text-xs">
                          <span className="text-slate-400">
                            {role === 'technical' ? '技术' : role === 'fundamental' ? '基本面' : role === 'valuation' ? '估值' : '事件'} ·
                          </span>
                          <span className="text-slate-600"> {view.view}</span>
                          <span className="text-slate-400">（引用：{(view.cites || []).join('、')}）</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {entry.position_cap_pct != null && (
                    <p className="text-xs text-slate-500">仓位上限：{formatNumber(entry.position_cap_pct, 0)}%</p>
                  )}
                  {entry.committee_conditions?.length > 0 && (
                    <ul className="text-xs text-slate-500 list-disc pl-4 space-y-0.5">
                      {entry.committee_conditions.map((cond: string, i: number) => <li key={i}>{cond}</li>)}
                    </ul>
                  )}
                </div>
              )
            })}
          </div>
        </SectionCard>
      )}
      {/* 证据抽屉：每个数字可溯源 */}
      {Object.keys(evidenceIndex).length > 0 && (
        <SectionCard icon={Hash} title="证据抽屉（每个数字可溯源）">
          <div className="space-y-2">
            {filterEntries(Object.entries(evidenceIndex)).map(([sym, records]: [string, any]) => (
              <div key={sym} className="border border-slate-200 rounded-lg">
                <button
                  onClick={() => setOpenEvidence(openEvidence === sym ? null : sym)}
                  className="w-full flex items-center justify-between px-3 py-2 text-sm font-medium hover:bg-slate-50 rounded-lg"
                >
                  <span>{sym} · {records.length} 条证据</span>
                  <span className="text-xs text-slate-400">{openEvidence === sym ? '收起' : '展开'}</span>
                </button>
                {openEvidence === sym && (
                  <div className="px-3 pb-3 overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-left text-slate-400 border-b border-slate-200">
                          <th className="py-1 pr-3">指标</th>
                          <th className="py-1 pr-3">数值</th>
                          <th className="py-1 pr-3">单位</th>
                          <th className="py-1 pr-3">as_of</th>
                          <th className="py-1 pr-3">来源</th>
                          <th className="py-1">公式</th>
                        </tr>
                      </thead>
                      <tbody>
                        {records.map((rec: any, i: number) => (
                          <tr key={rec.metric_id || i} className="border-b border-slate-100 align-top">
                            <td className="py-1 pr-3 font-medium text-slate-700">{rec.name}</td>
                            <td className="py-1 pr-3">{rec.value ?? '—'}</td>
                            <td className="py-1 pr-3 text-slate-500">{rec.unit}</td>
                            <td className="py-1 pr-3 text-slate-500">{String(rec.as_of || '').slice(0, 10)}</td>
                            <td className="py-1 pr-3 text-slate-500">{rec.source}</td>
                            <td className="py-1 text-slate-400">{rec.formula}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ))}
          </div>
        </SectionCard>
      )}
    </div>
  )
}

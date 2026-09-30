'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'
import {
  formatNumber, formatPercent, formatCurrency, currencyForSymbol,
} from '@/lib/format'
import type { AnalysisResult } from './types'
import { MarketOverview } from './MarketOverview'
import { AnalysisDetail } from './AnalysisDetail'
import { SentimentAnalysis } from './SentimentAnalysis'
import { RiskAssessment } from './RiskAssessment'
import { CatalystTimeline } from './CatalystTimeline'
import type { SymbolCatalysts } from './types'
import { ReportSkeleton } from './ReportSkeleton'
import { ConsensusBlock } from './report-shared'
import { BackToTop } from '@/components/layout/BackToTop'
import {
  ArrowLeft, CheckCircle2, AlertCircle, TrendingUp, TrendingDown,
  Minus, Activity, Target, Shield, BarChart3, Newspaper, Database,
  Brain, FileText, Clock, DollarSign, PieChart, Zap, Printer
} from 'lucide-react'

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000') + '/api'

// 智能体中文名称
const AGENT_NAMES: Record<string, string> = {
  data_collection: '数据采集',
  technical_analysis: '技术分析',
  fundamental_analysis: '基本面分析',
  sentiment_analysis: '情绪分析',
  risk_assessment: '风险评估',
  research_synthesis: '研究综合',
  decision_making: '决策制定',
  report_generation: '报告生成'
}

// 智能体图标
const AGENT_ICONS: Record<string, any> = {
  data_collection: Database,
  technical_analysis: BarChart3,
  fundamental_analysis: PieChart,
  sentiment_analysis: Newspaper,
  risk_assessment: Shield,
  research_synthesis: Zap,
  decision_making: Brain,
  report_generation: FileText
}

/* ── Pipeline Result View (original) ──────────────────────────── */

export function PipelineResultPage({ threadId }: { threadId: string | null }) {
  const router = useRouter()
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedSection, setExpandedSection] = useState<string | null>(null)
  // Set when the result came from the SQLite history archive rather than
  // the in-memory workflow cache (lost on every server restart).
  const [historyDate, setHistoryDate] = useState<string | null>(null)

  useEffect(() => {
    if (!threadId) {
      setLoading(false)
      return
    }

    const fetchResult = async () => {
      try {
        const res = await fetch(`${API_BASE}/analysis/result/${threadId}`)
        if (res.status === 404) {
          // The in-memory workflow cache is lost on restart; the history
          // archive stores the same result shape. Fall back before giving up.
          const hres = await fetch(`${API_BASE}/history/${threadId}`)
          if (hres.ok) {
            const hdata = await hres.json()
            const archived = hdata?.result
            if (archived && typeof archived === 'object' && Object.keys(archived).length > 0) {
              if (archived.error) {
                setError(`该次分析运行失败（历史记录）— ${archived.error}`)
              } else {
                setResult(archived as AnalysisResult)
                setHistoryDate(hdata.created_at ?? null)
              }
              return
            }
          }
          setError('未找到分析结果')
          return
        }
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`)
        }
        const data = await res.json()
        setResult(data)
        setError(null)
      } catch (e) {
        console.error('Failed to fetch result:', e)
        setError(e instanceof Error ? e.message : '未知错误')
      } finally {
        setLoading(false)
      }
    }

    fetchResult()
  }, [threadId])

  const getFirstDecision = () => {
    if (!result?.decision?.decisions) return null
    const symbols = Object.keys(result.decision.decisions)
    if (symbols.length === 0) return null
    return result.decision.decisions[symbols[0]]
  }

  const decision = getFirstDecision()

  // 获取操作建议
  const getActionInfo = (action: string) => {
    const a = action?.toLowerCase() || 'hold'
    if (a.includes('buy')) return {
      text: '买入',
      color: 'text-green-600',
      bg: 'bg-green-50 border-green-200',
      icon: TrendingUp
    }
    if (a.includes('sell')) return {
      text: '卖出',
      color: 'text-red-600',
      bg: 'bg-red-50 border-red-200',
      icon: TrendingDown
    }
    return {
      text: '持有',
      color: 'text-amber-600',
      bg: 'bg-amber-50 border-amber-200',
      icon: Minus
    }
  }

  // 获取得分颜色
  const getScoreColor = (score: number | undefined) => {
    if (score === undefined) return 'text-gray-400'
    if (score >= 50) return 'text-green-600'
    if (score >= 0) return 'text-amber-600'
    return 'text-red-600'
  }

  // 加载状态
  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white">
        <main className="max-w-6xl mx-auto px-4 py-6">
          <Card>
            <CardContent className="p-6 md:p-8">
              <ReportSkeleton />
            </CardContent>
          </Card>
        </main>
      </div>
    )
  }

  // 错误状态
  if (error) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white p-6">
        <div className="max-w-md mx-auto">
          <Card className="border-red-200 bg-red-50">
            <CardContent className="p-6 text-center">
              <AlertCircle className="h-12 w-12 text-red-400 mx-auto mb-4" />
              <h2 className="text-lg font-semibold text-red-700 mb-2">加载失败</h2>
              <p className="text-red-600 mb-4">{error}</p>
              <Button onClick={() => router.push('/')}>开始新分析</Button>
            </CardContent>
          </Card>
        </div>
      </div>
    )
  }

  // 无结果
  if (!result) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white p-6">
        <div className="max-w-md mx-auto">
          <Card>
            <CardContent className="p-8 text-center">
              <p className="text-slate-500">未指定分析结果</p>
              <Button className="mt-4" onClick={() => router.push('/')}>开始新分析</Button>
            </CardContent>
          </Card>
        </div>
      </div>
    )
  }

  const actionInfo = getActionInfo(decision?.action || '')
  const ActionIcon = actionInfo.icon
  const portfolio = result.decision?.portfolio_summary
  const weights = result.decision?.dimension_weights
  const allDecisions = Object.values(result.decision?.decisions ?? {})
  const isMultiSymbol = (portfolio?.total_symbols ?? allDecisions.length) > 1

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white">
      {/* 顶部导航 */}
      <header className="bg-white border-b sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="icon" className="no-print" onClick={() => router.push('/')}>
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <div>
              <h1 className="text-xl font-bold text-slate-900">分析报告</h1>
              <p className="text-sm text-slate-500">
                {result.symbols?.join('、')} · {threadId?.slice(0, 12)}...
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {historyDate && (
              <Badge variant="outline" className="text-xs text-slate-500" title={`历史存档 · 生成于 ${historyDate}`}>
                历史记录 · {historyDate.slice(0, 10)}
              </Badge>
            )}
            <Button
              variant="outline"
              size="sm"
              className="no-print h-8"
              onClick={() => window.print()}
              title="打印或另存为 PDF(自动隐藏导航与操作区)"
            >
              <Printer className="h-3.5 w-3.5 mr-1.5" />
              导出 PDF
            </Button>
            {result.execution_metadata?.execution_time && (
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <Clock className="h-4 w-4" />
                <span>{result.execution_metadata.execution_time.toFixed(1)}秒</span>
              </div>
            )}
          </div>
        </div>
      </header>

      {result.execution_metadata?.agent_timings &&
        Object.keys(result.execution_metadata.agent_timings).length > 0 && (
          <div className="max-w-6xl mx-auto px-4 pt-4 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
            <span className="font-medium text-slate-600">耗时分解</span>
            {Object.entries(result.execution_metadata.agent_timings)
              .sort((a, b) => b[1] - a[1])
              .map(([name, secs]) => (
                <span
                  key={name}
                  className="rounded-full bg-slate-100 px-2 py-0.5 font-mono"
                  title={`${name} 阶段耗时`}
                >
                  {name} {secs.toFixed(1)}s
                </span>
              ))}
          </div>
        )}

      <main className="max-w-6xl mx-auto px-4 py-6 space-y-6">
        {/* 组合概览 — 多标的 run 的顶层视角（portfolio_summary 首个消费方） */}
        {isMultiSymbol && portfolio && (
          <Card className="border-slate-200">
            <CardContent className="p-4 space-y-3">
              <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
                <div className="text-sm font-semibold text-slate-700">组合概览</div>
                <div className="flex items-center gap-4 text-sm font-medium">
                  <span className="text-green-600">{portfolio.buy_recommendations} 买入</span>
                  <span className="text-amber-600">{portfolio.hold_recommendations} 持有</span>
                  <span className="text-red-600">{portfolio.sell_recommendations} 卖出</span>
                </div>
                <div className="text-sm text-slate-500">
                  共 {portfolio.total_symbols} 个标的 · 平均置信度{' '}
                  <span className="font-semibold">{formatPercent(portfolio.avg_confidence, 0)}</span>
                </div>
              </div>
              <div>
                <div className="text-xs font-medium text-slate-500 mb-1.5">全部标的建议</div>
                <div className="space-y-1">
                  {allDecisions.map((d) => {
                    const info = getActionInfo(d.action)
                    return (
                      <div
                        key={d.symbol}
                        className="flex items-center justify-between text-sm py-1 border-b border-slate-100 last:border-0"
                      >
                        <span className="font-medium text-slate-700">{d.symbol}</span>
                        <span className="flex items-center gap-4">
                          <span className={info.color}>{info.text}</span>
                          <span className="text-slate-500">{formatPercent(d.confidence, 0)}</span>
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
              <p className="text-[11px] text-slate-400">
                下方核心建议卡为首标的的明细；每个标的的完整分解见「决策综合」叙事。
              </p>
            </CardContent>
          </Card>
        )}
        {/* 核心投资建议卡片 */}
        {decision && (
          <Card className={cn("border-2", actionInfo.bg)}>
            <CardContent className="p-6">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-4">
                  <div className={cn("p-4 rounded-full bg-white shadow-sm", actionInfo.color)}>
                    <ActionIcon className="h-8 w-8" />
                  </div>
                  <div>
                    <p className="text-sm text-slate-500 mb-1">投资建议</p>
                    <h2 className={cn("text-3xl font-bold", actionInfo.color)}>
                      {actionInfo.text}
                    </h2>
                    <p className="text-slate-600 mt-1">
                      置信度 <span className="font-semibold">{formatPercent(decision.confidence, 1)}</span>
                    </p>
                  </div>
                </div>
                <Badge variant="outline" className="text-sm">
                  {decision.symbol}
                </Badge>
              </div>

              {/* 组件得分 */}
              {decision.component_scores && (
                <div className="mt-6 grid grid-cols-3 gap-4">
                  <div className="bg-white rounded-lg p-4 border">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm text-slate-500">技术面</span>
                      <BarChart3 className="h-4 w-4 text-slate-400" />
                    </div>
                    <p className={cn("text-2xl font-bold", getScoreColor(decision.component_scores.technical))}>
                      {formatNumber(decision.component_scores.technical, 0)}
                    </p>
                    <Progress
                      value={Math.abs(decision.component_scores.technical || 0)}
                      className="mt-2 h-1"
                    />
                  </div>
                  <div className="bg-white rounded-lg p-4 border">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm text-slate-500">基本面</span>
                      <PieChart className="h-4 w-4 text-slate-400" />
                    </div>
                    <p className={cn("text-2xl font-bold", getScoreColor(decision.component_scores.fundamental))}>
                      {formatNumber(decision.component_scores.fundamental, 0)}
                    </p>
                    <Progress
                      value={Math.abs(decision.component_scores.fundamental || 0)}
                      className="mt-2 h-1"
                    />
                  </div>
                  <div className="bg-white rounded-lg p-4 border">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm text-slate-500">市场情绪</span>
                      <Newspaper className="h-4 w-4 text-slate-400" />
                    </div>
                    <p className={cn("text-2xl font-bold", getScoreColor(decision.component_scores.sentiment))}>
                      {formatNumber(decision.component_scores.sentiment, 0)}
                    </p>
                    <Progress
                      value={Math.abs(decision.component_scores.sentiment || 0)}
                      className="mt-2 h-1"
                    />
                  </div>
                </div>
              )}

              {/* 维度权重 — 上面三个分各占多少（dimension_weights 首个消费方） */}
              {weights && (
                <div className="mt-6 p-4 bg-white rounded-lg border space-y-2.5">
                  <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                    <span className="text-sm font-medium text-slate-700">
                      维度权重 · {weights.mode === 'adaptive' ? 'IC 自适应' : '固定混合'}
                    </span>
                    {weights.mode === 'adaptive' ? (
                      <span className="text-xs text-slate-500">
                        λ={weights.lambda?.toFixed(2)} · 证据 {weights.runs_evaluated ?? '—'} runs · 前瞻{' '}
                        {weights.horizon_bars ?? '—'} 日
                      </span>
                    ) : (
                      weights.reason && (
                        <span
                          className="text-xs text-slate-400 max-w-md truncate"
                          title={weights.reason ?? undefined}
                        >
                          {weights.reason}
                        </span>
                      )
                    )}
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    {(
                      [
                        { key: 'technical', label: '技术面' },
                        { key: 'fundamental', label: '基本面' },
                        { key: 'sentiment', label: '情绪' },
                      ] as const
                    ).map(({ key, label }) => {
                      const w = weights.weights[key]
                      const stat = weights.per_dimension?.[key]
                      const delta =
                        w !== undefined && weights.mode === 'adaptive'
                          ? w - (weights.static_weights[key] ?? 0)
                          : 0
                      return (
                        <div key={key} className="rounded-md bg-slate-50 px-3 py-2">
                          <div className="flex items-baseline justify-between">
                            <span className="text-xs text-slate-500">{label}</span>
                            <span className="text-sm font-semibold text-slate-700">
                              {formatPercent(w, 0)}
                            </span>
                          </div>
                          {weights.mode === 'adaptive' && stat?.qualified && (
                            <p className="text-[11px] text-slate-400 mt-0.5">
                              IC {stat.ic_mean?.toFixed(2) ?? '—'} · {stat.runs} runs
                              {delta !== 0 && (
                                <span className={delta > 0 ? 'text-green-600' : 'text-red-500'}>
                                  {' '}
                                  {delta > 0 ? '↑' : '↓'}
                                  {formatPercent(Math.abs(delta), 0)}
                                </span>
                              )}
                            </p>
                          )}
                        </div>
                      )
                    })}
                  </div>
                  <p className="text-[11px] text-slate-400">
                    复合分 = 各维度分 × 权重 + 风险修饰 10%；权重由历史 IC 证据门控（维度证据不足 12 runs
                    时保持固定 45/30/15）。
                  </p>
                </div>
              )}

              {/* 价格目标 */}
              {decision.price_targets && (
                <div className="mt-6 flex items-center gap-8 p-4 bg-white rounded-lg border">
                  <div className="flex items-center gap-2">
                    <DollarSign className="h-5 w-5 text-slate-400" />
                    <div>
                      <p className="text-xs text-slate-500">当前价格</p>
                      <p className="text-lg font-semibold">{formatCurrency(decision.price_targets.current, currencyForSymbol(decision.symbol))}</p>
                    </div>
                  </div>
                  {decision.price_targets.target && (
                    <div className="flex items-center gap-2">
                      <Target className="h-5 w-5 text-green-500" />
                      <div>
                        <p className="text-xs text-slate-500">目标价</p>
                        <p className="text-lg font-semibold text-green-600">{formatCurrency(decision.price_targets.target, currencyForSymbol(decision.symbol))}</p>
                      </div>
                    </div>
                  )}
                  {decision.price_targets.stop_loss && (
                    <div className="flex items-center gap-2">
                      <Shield className="h-5 w-5 text-red-500" />
                      <div>
                        <p className="text-xs text-slate-500">止损价</p>
                        <p className="text-lg font-semibold text-red-600">{formatCurrency(decision.price_targets.stop_loss, currencyForSymbol(decision.symbol))}</p>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* 仓位建议 */}
              {decision.position_size?.percentage_of_portfolio && (
                <div className="mt-4 flex items-center gap-2 text-sm text-slate-600">
                  <PieChart className="h-4 w-4" />
                  <span>建议仓位：<strong>{decision.position_size.percentage_of_portfolio}%</strong> 的投资组合</span>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* 两列布局 */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* 左侧：分析详情 */}
          <div className="lg:col-span-2 space-y-4">
            {/* 市场概览 */}
            {result.report?.sections?.overview && (
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Activity className="h-4 w-4" />
                    市场概览
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <MarketOverview data={result.report.sections.overview} />
                </CardContent>
              </Card>
            )}

            {/* 催化剂时间轴 —— 事件标注（by_symbol 逐标的卡；旧报告整键缺席
             * 时 map 为空，渲染面零扰动） */}
            {Object.entries(result.report?.sections?.catalysts?.by_symbol || {}).map(([sym, c]) => (
              <CatalystTimeline key={sym} symbol={sym} data={c as SymbolCatalysts} />
            ))}

            {/* 技术分析 */}
            {result.technical_analysis && (
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <BarChart3 className="h-4 w-4" />
                    技术分析
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <AnalysisDetail
                    data={result.technical_analysis}
                    expanded={expandedSection === 'technical'}
                    onToggle={() => setExpandedSection(expandedSection === 'technical' ? null : 'technical')}
                  />
                </CardContent>
              </Card>
            )}

            {/* 基本面分析 */}
            {result.fundamental_analysis && (
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <PieChart className="h-4 w-4" />
                    基本面分析
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {Object.entries(result.report?.sections?.fundamental_analysis?.by_symbol || {})
                    .filter(([, f]: any) => f?.consensus)
                    .map(([sym, f]: [string, any]) => (
                      <div key={sym} className="mb-3">
                        <ConsensusBlock symbol={sym} consensus={f.consensus} />
                      </div>
                    ))}
                  <AnalysisDetail
                    data={result.fundamental_analysis}
                    expanded={expandedSection === 'fundamental'}
                    onToggle={() => setExpandedSection(expandedSection === 'fundamental' ? null : 'fundamental')}
                  />
                </CardContent>
              </Card>
            )}

            {/* 情绪分析 */}
            {result.sentiment_analysis && (
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Newspaper className="h-4 w-4" />
                    市场情绪
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <SentimentAnalysis data={result.sentiment_analysis} />
                </CardContent>
              </Card>
            )}

            {/* 风险评估 */}
            {result.risk_assessment && (
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Shield className="h-4 w-4" />
                    风险评估
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <RiskAssessment data={result.risk_assessment} />
                </CardContent>
              </Card>
            )}
          </div>

          {/* 右侧：执行状态（打印时隐藏——运营面板不进报告） */}
          <div className="space-y-4 no-print">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">执行状态</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {Object.entries(result.agent_status || {}).map(([agent, status]) => {
                    const Icon = AGENT_ICONS[agent] || Activity
                    const isCompleted = status === 'completed'

                    return (
                      <div
                        key={agent}
                        className={cn(
                          "flex items-center gap-3 p-3 rounded-lg border transition-colors",
                          isCompleted ? "bg-green-50 border-green-100" : "bg-red-50 border-red-100"
                        )}
                      >
                        <div className={cn(
                          "p-2 rounded-full",
                          isCompleted ? "bg-green-100" : "bg-red-100"
                        )}>
                          {isCompleted ? (
                            <CheckCircle2 className="h-4 w-4 text-green-600" />
                          ) : (
                            <AlertCircle className="h-4 w-4 text-red-600" />
                          )}
                        </div>
                        <div className="flex-1">
                          <p className="text-sm font-medium">
                            {AGENT_NAMES[agent] || agent}
                          </p>
                          <p className={cn(
                            "text-xs",
                            isCompleted ? "text-green-600" : "text-red-600"
                          )}>
                            {isCompleted ? '已完成' : '未完成'}
                          </p>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </CardContent>
            </Card>

            {/* 操作按钮 */}
            <div className="space-y-2">
              <Button
                className="w-full"
                variant="outline"
                onClick={() => router.push(`/monitoring?thread_id=${threadId}`)}
              >
                查看执行日志
              </Button>
              <Button
                className="w-full"
                onClick={() => router.push('/')}
              >
                开始新分析
              </Button>
            </div>
          </div>
        </div>
      </main>
      <BackToTop />
    </div>
  )
}

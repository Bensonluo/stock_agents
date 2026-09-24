'use client'

import { useState, useEffect, Suspense, type ReactNode } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  Loader2, ArrowLeft, CheckCircle2, AlertCircle, TrendingUp, TrendingDown,
  Minus, Activity, Target, Shield, BarChart3, Newspaper, Database,
  Brain, FileText, Clock, DollarSign, Percent, PieChart, Wrench, Zap, Hash
} from 'lucide-react'
import { cn, API } from '@/lib/utils'
import type { ReactResultResponse } from '@/lib/utils'
import { ResponsiveContainer, AreaChart, Area, YAxis } from 'recharts'

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000') + '/api'

// 格式化数字
function formatNumber(num: number | undefined, decimals = 2): string {
  if (num === undefined || num === null || isNaN(num as number)) return '-'
  return (num as number).toFixed(decimals)
}

// 格式化比率（0.31 → "31.0%"；VaR/回撤为负值原样带符号）
function formatPercent(num: number | undefined | null, decimals = 1): string {
  if (num === undefined || num === null || isNaN(num)) return '-'
  return `${(num * 100).toFixed(decimals)}%`
}

// 格式化成交额（按币种本地化缩写：1500000 → "150万" / "1.5M"）
function formatAdv(num: number | undefined | null, currency: string): string {
  if (num === undefined || num === null || isNaN(num)) return '-'
  if (currency === 'CNY') return `${(num / 10000).toFixed(0)}万`
  if (num >= 1e9) return `${(num / 1e9).toFixed(1)}B`
  return `${(num / 1e6).toFixed(1)}M`
}

// 格式化货币（CNY → ¥，HKD → HK$，其余 $）
function formatCurrency(num: number | undefined, currency?: string): string {
  if (num === undefined || num === null || isNaN(num)) return '-'
  const symbol = currency === 'CNY' ? '¥' : currency === 'HKD' ? 'HK$' : '$'
  return `${symbol}${num.toFixed(2)}`
}

// 按标的推断币种（镜像后端 _liquidity_block 语义）：6 位数字 → CNY，
// .HK → HKD，其余 USD。仅在 overview 未带 currency 时兜底。
function currencyForSymbol(symbol: string): string {
  if (symbol.toUpperCase().includes('.HK')) return 'HKD'
  if (/^\d{6}$/.test(symbol)) return 'CNY'
  return 'USD'
}

// 格式化市值（CNY 按亿，USD 按 B —— A 股市值以亿计是本土惯例）
function formatMarketCap(num: number | undefined | null, currency?: string): string {
  if (num === undefined || num === null || isNaN(num)) return '-'
  if (currency === 'CNY') return `¥${(num / 1e8).toFixed(0)}亿`
  if (num >= 1e12) return `$${(num / 1e12).toFixed(2)}T`
  return `$${(num / 1e9).toFixed(2)}B`
}

// Sparkline 线色（SVG hex，趋势同色系：emerald-500 / red-500 / slate-400）
function sparkColor(trend: string | undefined): string {
  if (trend === 'bullish' || trend === 'strong_bullish') return '#10b981'
  if (trend === 'bearish' || trend === 'strong_bearish') return '#ef4444'
  return '#94a3b8'
}

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

interface AnalysisResult {
  thread_id: string
  query: string
  symbols: string[]
  decision?: {
    decisions?: Record<string, {
      symbol: string
      action: string
      confidence: number
      score: number
      component_scores?: {
        technical?: number
        fundamental?: number
        sentiment?: number
      }
      price_targets?: {
        current: number
        stop_loss?: number
        target?: number
      }
      position_size?: {
        percentage_of_portfolio?: number
        sizing_rationale?: string
      }
    }>
  }
  report?: {
    sections?: Record<string, any>
  }
  technical_analysis?: any
  fundamental_analysis?: any
  sentiment_analysis?: any
  risk_assessment?: any
  agent_status: Record<string, string>
  execution_metadata?: {
    execution_time?: number
    had_errors?: boolean
  }
}

/* ── ReAct Result View (Markdown Report) ──────────────────────── */

function ReactResultPage({ threadId }: { threadId: string }) {
  const router = useRouter()
  const [result, setResult] = useState<ReactResultResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchResult = async () => {
      try {
        const data = await API.getReactResult(threadId)
        setResult(data)
      } catch (e) {
        setError(e instanceof Error ? e.message : '未知错误')
      } finally {
        setLoading(false)
      }
    }
    fetchResult()
  }, [threadId])

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="h-10 w-10 animate-spin text-blue-500 mx-auto" />
          <p className="mt-4 text-slate-600">正在加载分析报告...</p>
        </div>
      </div>
    )
  }

  if (error || !result) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white p-6">
        <div className="max-w-md mx-auto">
          <Card className="border-red-200 bg-red-50">
            <CardContent className="p-6 text-center">
              <AlertCircle className="h-12 w-12 text-red-400 mx-auto mb-4" />
              <h2 className="text-lg font-semibold text-red-700 mb-2">加载失败</h2>
              <p className="text-red-600 mb-4">{error || '未找到结果'}</p>
              <Button onClick={() => router.push('/')}>开始新分析</Button>
            </CardContent>
          </Card>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white">
      <header className="bg-white border-b sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="icon" onClick={() => router.push('/')}>
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <div>
              <h1 className="text-xl font-bold text-slate-900">ReAct 分析报告</h1>
              <p className="text-sm text-slate-500">{threadId.slice(0, 24)}...</p>
            </div>
          </div>
          <Badge variant="success">已完成</Badge>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 py-6">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          {/* Main content: Markdown report */}
          <div className="lg:col-span-3">
            <Card>
              <CardContent className="p-6 md:p-8">
                <ReactReport answer={result.answer} report={result.report} />
              </CardContent>
            </Card>
          </div>

          {/* Sidebar: Metadata */}
          <div className="space-y-4">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Zap className="h-4 w-4" />
                  分析概要
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center gap-3">
                  <Hash className="h-4 w-4 text-muted-foreground" />
                  <div>
                    <p className="text-xs text-muted-foreground">迭代次数</p>
                    <p className="font-semibold">{result.iterations}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <DollarSign className="h-4 w-4 text-muted-foreground" />
                  <div>
                    <p className="text-xs text-muted-foreground">估算成本</p>
                    <p className="font-semibold">${result.cost.toFixed(4)}</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Wrench className="h-4 w-4" />
                  已调用工具
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-2">
                  {result.tools_used.map((tool, i) => (
                    <Badge key={i} variant="outline" className="font-mono text-xs">
                      {tool}
                    </Badge>
                  ))}
                  {result.tools_used.length === 0 && (
                    <p className="text-sm text-muted-foreground">无工具调用</p>
                  )}
                </div>
              </CardContent>
            </Card>

            <div className="space-y-2">
              <Button
                className="w-full"
                variant="outline"
                onClick={() => router.push(`/monitoring?thread_id=${threadId}&mode=react`)}
              >
                查看执行详情
              </Button>
              <Button className="w-full" onClick={() => router.push('/')}>
                开始新分析
              </Button>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}

/* ── Pipeline Result View (original) ──────────────────────────── */

function ResultPage() {
  const searchParams = useSearchParams()
  const threadId = searchParams.get('thread_id')
  const mode = searchParams.get('mode')

  if (mode === 'react' && threadId) {
    return <ReactResultPage threadId={threadId} />
  }

  return <PipelineResultPage threadId={threadId} />
}

function PipelineResultPage({ threadId }: { threadId: string | null }) {
  const router = useRouter()
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedSection, setExpandedSection] = useState<string | null>(null)

  useEffect(() => {
    if (!threadId) {
      setLoading(false)
      return
    }

    const fetchResult = async () => {
      try {
        const res = await fetch(`${API_BASE}/analysis/result/${threadId}`)
        if (!res.ok) {
          if (res.status === 404) {
            setError('未找到分析结果')
          } else {
            throw new Error(`HTTP ${res.status}`)
          }
          return
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
      <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="h-10 w-10 animate-spin text-blue-500 mx-auto" />
          <p className="mt-4 text-slate-600">正在加载分析结果...</p>
        </div>
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

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white">
      {/* 顶部导航 */}
      <header className="bg-white border-b sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="icon" onClick={() => router.push('/')}>
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <div>
              <h1 className="text-xl font-bold text-slate-900">分析报告</h1>
              <p className="text-sm text-slate-500">
                {result.symbols?.join('、')} · {threadId?.slice(0, 12)}...
              </p>
            </div>
          </div>
          {result.execution_metadata?.execution_time && (
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <Clock className="h-4 w-4" />
              <span>{result.execution_metadata.execution_time.toFixed(1)}秒</span>
            </div>
          )}
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 py-6 space-y-6">
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
                      置信度 <span className="font-semibold">{formatNumber(decision.confidence, 1)}%</span>
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

          {/* 右侧：执行状态 */}
          <div className="space-y-4">
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
    </div>
  )
}

// ReAct 结构化报告组件 —— 把 answer(JSON)渲染成人类可读的投资报告
function ReactReport({ answer, report: structuredReport }: {
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

  const filterEntries = (entries: [string, any][]): [string, any][] =>
    activeSymbol === 'all' ? entries : entries.filter(([s]) => s === activeSymbol)

  const actionZh = (a: string): string => {
    const m: Record<string, string> = {
      buy: '买入', add: '加仓', hold: '持有', reduce: '减仓', sell: '卖出',
      strong_buy: '强烈买入', strong_sell: '强烈卖出',
    }
    return m[String(a || '').toLowerCase()] || a || '持有'
  }
  const actionStyle = (a: string) => {
    const s = String(a || '').toLowerCase()
    if (['buy', 'add', 'strong_buy'].includes(s))
      return { ring: 'ring-green-200', color: 'text-green-700', bg: 'bg-green-100' }
    if (['sell', 'reduce', 'strong_sell'].includes(s))
      return { ring: 'ring-red-200', color: 'text-red-700', bg: 'bg-red-100' }
    return { ring: 'ring-amber-200', color: 'text-amber-700', bg: 'bg-amber-100' }
  }
  const trendZh = (t: string): string => {
    const s = String(t || '').toLowerCase()
    if (s.includes('bull') || s.includes('buy')) return '看涨'
    if (s.includes('bear') || s.includes('sell')) return '看跌'
    return '中性'
  }
  const trendColor = (t: string): string => {
    const s = String(t || '').toLowerCase()
    if (s.includes('bull') || s.includes('buy')) return 'text-green-600'
    if (s.includes('bear') || s.includes('sell')) return 'text-red-600'
    return 'text-amber-600'
  }
  const riskZh = (r: string): string => {
    const m: Record<string, string> = { very_low: '极低', low: '低', medium: '中', high: '高', very_high: '极高' }
    return m[String(r || '').toLowerCase()] || r || '中'
  }
  const riskStyle = (r: string) => {
    const s = String(r || '').toLowerCase()
    if (['very_low', 'low'].includes(s)) return { color: 'text-green-700', bg: 'bg-green-100' }
    if (['high', 'very_high'].includes(s)) return { color: 'text-red-700', bg: 'bg-red-100' }
    return { color: 'text-amber-700', bg: 'bg-amber-100' }
  }
  const sentimentZh = (s: string): string => {
    const v = String(s || '').toLowerCase()
    if (v.includes('very_positive')) return '非常积极'
    if (v.includes('positive')) return '积极'
    if (v.includes('very_negative')) return '非常消极'
    if (v.includes('negative')) return '消极'
    return '中性'
  }
  const scoreOf = (v: any): number | null => {
    if (typeof v === 'number') return v
    if (v && typeof v === 'object' && typeof v.score === 'number') return v.score
    return null
  }

  const SectionCard = ({ icon: Icon, title, children }: { icon: any; title: string; children: ReactNode }) => (
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
                </div>
              </div>
            ))}
          </div>
          {overview.analysis_date && (
            <p className="text-xs text-slate-400 mt-3">分析日期：{overview.analysis_date}</p>
          )}
        </SectionCard>
      )}

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
                          <div className="flex justify-between"><span className="text-slate-500">年化 α</span><span className={cn('font-medium', r.alpha_annualized >= 0 ? 'text-green-600' : 'text-red-600')}>{formatPercent(r.alpha_annualized)}</span></div>
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

// 市场概览组件
function MarketOverview({ data }: { data: any }) {
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
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// 分析详情组件
function AnalysisDetail({ data, expanded, onToggle }: { data: any; expanded: boolean; onToggle: () => void }) {
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

// 情绪分析组件
function SentimentAnalysis({ data }: { data: any }) {
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

// 风险评估组件
function RiskAssessment({ data }: { data: any }) {
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
    </div>
  )
}

export default function ResultPageWrapper() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white flex items-center justify-center">
        <Loader2 className="h-10 w-10 animate-spin text-blue-500" />
      </div>
    }>
      <ResultPage />
    </Suspense>
  )
}

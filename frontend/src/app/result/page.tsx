'use client'

import { useState, useEffect, Suspense } from 'react'
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

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000') + '/api'

// 格式化数字
function formatNumber(num: number | undefined, decimals = 2): string {
  if (num === undefined || num === null || isNaN(num as number)) return '-'
  return (num as number).toFixed(decimals)
}

// 格式化货币
function formatCurrency(num: number | undefined): string {
  if (num === undefined || num === null || isNaN(num as number)) return '-'
  return `$${(num as number).toFixed(2)}`
}

// 智能体中文名称
const AGENT_NAMES: Record<string, string> = {
  data_collection: '数据采集',
  technical_analysis: '技术分析',
  fundamental_analysis: '基本面分析',
  sentiment_analysis: '情绪分析',
  risk_assessment: '风险评估',
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
                <div className="react-markdown">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {result.answer}
                  </ReactMarkdown>
                </div>
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
  const router = useRouter()
  const searchParams = useSearchParams()
  const threadId = searchParams.get('thread_id')
  const mode = searchParams.get('mode')

  // Route to ReAct view if mode=react
  if (mode === 'react' && threadId) {
    return <ReactResultPage threadId={threadId} />
  }

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
                      <p className="text-lg font-semibold">{formatCurrency(decision.price_targets.current)}</p>
                    </div>
                  </div>
                  {decision.price_targets.target && (
                    <div className="flex items-center gap-2">
                      <Target className="h-5 w-5 text-green-500" />
                      <div>
                        <p className="text-xs text-slate-500">目标价</p>
                        <p className="text-lg font-semibold text-green-600">{formatCurrency(decision.price_targets.target)}</p>
                      </div>
                    </div>
                  )}
                  {decision.price_targets.stop_loss && (
                    <div className="flex items-center gap-2">
                      <Shield className="h-5 w-5 text-red-500" />
                      <div>
                        <p className="text-xs text-slate-500">止损价</p>
                        <p className="text-lg font-semibold text-red-600">{formatCurrency(decision.price_targets.stop_loss)}</p>
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

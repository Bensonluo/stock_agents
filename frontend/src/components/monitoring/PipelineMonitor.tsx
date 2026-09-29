'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'
import type { WorkflowState, LogEntry } from './types'
import { useDataSourceHealth } from './useDataSourceHealth'
import { DataSourceHealthPanel } from './DataSourceHealthPanel'
import { AgentHealthPanel } from './AgentHealthPanel'
import {
  Database, TrendingUp, BarChart3, MessageSquare, Shield, Brain, FileText,
  Loader2, CheckCircle2, XCircle, Clock, ArrowLeft, Zap
} from 'lucide-react'

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000') + '/api'

// 与结果页 AGENT_NAMES 同词表——同一 agent 在两个页面必须同名
const AGENTS = [
  { key: 'data_collection', name: '数据采集', icon: Database },
  { key: 'technical_analysis', name: '技术分析', icon: TrendingUp },
  { key: 'fundamental_analysis', name: '基本面分析', icon: BarChart3 },
  { key: 'sentiment_analysis', name: '情绪分析', icon: MessageSquare },
  { key: 'risk_assessment', name: '风险评估', icon: Shield },
  { key: 'research_synthesis', name: '研究综合', icon: Zap },
  { key: 'decision_making', name: '决策制定', icon: Brain },
  { key: 'report_generation', name: '报告生成', icon: FileText },
]

const STATUS_ZH: Record<string, string> = {
  pending: '等待中',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  degraded: '已降级',
  loading: '加载中',
}

const statusZh = (status: string | undefined) =>
  STATUS_ZH[(status || 'loading').toLowerCase()] || status || '加载中'

export function PipelineMonitor({ threadId }: { threadId: string }) {
  const router = useRouter()
  const [workflow, setWorkflow] = useState<WorkflowState | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const { health: dataSourceHealth, fetchHealth: fetchDataSourceHealth } = useDataSourceHealth()
  const [error, setError] = useState<string | null>(null)
  const [polling, setPolling] = useState(true)

  const fetchWorkflow = useCallback(async () => {
    if (!threadId) return
    try {
      const res = await fetch(`${API_BASE}/monitor/workflow/${threadId}`)
      if (!res.ok) {
        if (res.status === 404) { setError('未找到工作流'); return }
        throw new Error(`HTTP ${res.status}`)
      }
      const data = await res.json()
      setWorkflow(data)
      setError(null)
      if (data.status === 'completed' || data.status === 'failed') setPolling(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : '未知错误')
    }
  }, [threadId])

  const fetchLogs = useCallback(async () => {
    if (!threadId) return
    try {
      const res = await fetch(`${API_BASE}/monitor/workflow/${threadId}/logs?limit=100`)
      if (res.ok) { const data = await res.json(); setLogs(data.logs || []) }
    } catch { /* ignore */ }
  }, [threadId])

  useEffect(() => {
    if (!threadId || !polling) return
    fetchWorkflow()
    fetchLogs()
    fetchDataSourceHealth()
    const interval = setInterval(() => {
      fetchWorkflow()
      fetchLogs()
      fetchDataSourceHealth()
    }, 1000)
    return () => clearInterval(interval)
  }, [threadId, polling, fetchWorkflow, fetchLogs, fetchDataSourceHealth])

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed': return <CheckCircle2 className="h-5 w-5 text-green-500" />
      case 'running': return <Loader2 className="h-5 w-5 text-blue-500 animate-spin" />
      case 'failed': return <XCircle className="h-5 w-5 text-red-500" />
      default: return <Clock className="h-5 w-5 text-gray-400" />
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'bg-green-500/10 border-green-500/50'
      case 'running': return 'bg-blue-500/10 border-blue-500/50'
      case 'failed': return 'bg-red-500/10 border-red-500/50'
      default: return 'bg-gray-500/10 border-gray-500/50'
    }
  }

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => router.push('/')}>
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <div>
            <h1 className="text-2xl font-bold">工作流监控</h1>
            <p className="text-sm text-muted-foreground font-mono">线程 {threadId.slice(0, 20)}...</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {polling && <Loader2 className="h-4 w-4 animate-spin text-blue-500" />}
          <Badge variant={workflow?.status === 'completed' ? 'success' : workflow?.status === 'failed' ? 'destructive' : 'default'}>
            {statusZh(workflow?.status)}
          </Badge>
        </div>
      </div>

      {error && (
        <Card className="border-red-500">
          <CardContent className="p-4 text-red-500">错误：{error}</CardContent>
        </Card>
      )}

      {workflow && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex justify-between">
              <span>整体进度</span>
              <span className="tabular-nums">{Math.round(workflow.progress)}%</span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Progress value={workflow.progress} className="h-2" />
            {(workflow.running_agents?.length ?? 0) > 1 && (
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <span className="text-xs text-muted-foreground">
                  并行执行中 · {workflow.running_agents!.length} 个智能体
                </span>
                {workflow.running_agents!.map(a => (
                  <span
                    key={a}
                    className="px-2 py-0.5 rounded-full bg-blue-500/10 border border-blue-500/30 text-xs text-blue-600"
                  >
                    {AGENTS.find(x => x.key === a)?.name || a}
                  </span>
                ))}
              </div>
            )}
            {workflow.phase === 'analysis_barrier' && (
              <div className="mt-3">
                <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/30 text-xs text-amber-600">
                  <Clock className="h-3 w-3" />
                  并行分析汇合中
                </span>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {AGENTS.map(agent => {
          const state = workflow?.agents?.[agent.key]
          const status = state?.status || 'pending'
          return (
            <Card key={agent.key} className={cn('border-2', getStatusColor(status))}>
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <div className="flex items-center justify-center w-10 h-10 rounded-full border-2 bg-background">
                    {status === 'running'
                      ? <Loader2 className="h-5 w-5 animate-spin text-blue-500" />
                      : <agent.icon className={cn(
                          'h-5 w-5',
                          status === 'completed' && 'text-green-500',
                          status === 'failed' && 'text-red-500',
                          status === 'pending' && 'text-gray-400'
                        )} />
                    }
                  </div>
                  <div className="flex-1">
                    <p className="font-medium text-sm">{agent.name}</p>
                    <p className="text-xs text-muted-foreground">{statusZh(status)}</p>
                  </div>
                  {getStatusIcon(status)}
                </div>
                {state?.error && <p className="mt-2 text-xs text-red-500 truncate">{state.error}</p>}
              </CardContent>
            </Card>
          )
        })}
      </div>

      <DataSourceHealthPanel health={dataSourceHealth} />

      <AgentHealthPanel />

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center justify-between">
            <span>执行日志</span>
            <span className="text-muted-foreground font-normal">{logs.length} 条</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-1 max-h-64 overflow-y-auto font-mono text-xs bg-muted/30 p-3 rounded">
            {logs.length === 0 ? (
              <p className="text-muted-foreground text-center py-4">暂无日志</p>
            ) : (
              logs.map((log, i) => (
                <div key={i} className={cn(
                  'py-1 border-b border-border/30 last:border-0',
                  log.level === 'error' && 'text-red-500',
                  log.level === 'warning' && 'text-yellow-500'
                )}>
                  <span className="text-muted-foreground">
                    {new Date(log.timestamp).toLocaleTimeString()}
                  </span>
                  <span className="text-primary mx-2">[{log.agent}]</span>
                  <span>{log.message}</span>
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>

      <div className="flex justify-center gap-4">
        <Button variant="outline" onClick={() => router.push('/')}>新建分析</Button>
        {workflow?.status === 'completed' && (
          <Button onClick={() => router.push(`/result?thread_id=${threadId}`)}>查看结果</Button>
        )}
      </div>
    </div>
  )
}

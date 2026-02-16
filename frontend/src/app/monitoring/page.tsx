'use client'

import { useState, useEffect, useCallback, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'
import {
  Database, TrendingUp, BarChart3, MessageSquare, Shield, Brain, FileText,
  Loader2, CheckCircle2, XCircle, Clock, RefreshCw, ArrowLeft
} from 'lucide-react'

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000') + '/api'

const AGENTS = [
  { key: 'data_collection', name: 'Data Collection', icon: Database },
  { key: 'technical_analysis', name: 'Technical Analysis', icon: TrendingUp },
  { key: 'fundamental_analysis', name: 'Fundamental Analysis', icon: BarChart3 },
  { key: 'sentiment_analysis', name: 'Sentiment Analysis', icon: MessageSquare },
  { key: 'risk_assessment', name: 'Risk Assessment', icon: Shield },
  { key: 'decision_making', name: 'Decision Making', icon: Brain },
  { key: 'report_generation', name: 'Report Generation', icon: FileText },
]

interface AgentState {
  name: string
  status: string
  started_at?: string
  completed_at?: string
  error?: string
}

interface WorkflowState {
  thread_id: string
  status: string
  agents: Record<string, AgentState>
  current_agent: string | null
  progress: number
  updated_at: string
}

interface LogEntry {
  timestamp: string
  agent: string
  level: string
  message: string
}

function MonitoringPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const threadId = searchParams.get('thread_id')

  const [workflow, setWorkflow] = useState<WorkflowState | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [polling, setPolling] = useState(true)

  // 获取工作流状态
  const fetchWorkflow = useCallback(async () => {
    if (!threadId) return

    try {
      const res = await fetch(`${API_BASE}/monitor/workflow/${threadId}`)
      if (!res.ok) {
        if (res.status === 404) {
          setError('Workflow not found')
          return
        }
        throw new Error(`HTTP ${res.status}`)
      }
      const data = await res.json()
      setWorkflow(data)
      setError(null)

      // 如果完成或失败，停止轮询
      if (data.status === 'completed' || data.status === 'failed') {
        setPolling(false)
      }
    } catch (e) {
      console.error('Failed to fetch workflow:', e)
      setError(e instanceof Error ? e.message : 'Unknown error')
    }
  }, [threadId])

  // 获取日志
  const fetchLogs = useCallback(async () => {
    if (!threadId) return

    try {
      const res = await fetch(`${API_BASE}/monitor/workflow/${threadId}/logs?limit=100`)
      if (res.ok) {
        const data = await res.json()
        setLogs(data.logs || [])
      }
    } catch (e) {
      console.error('Failed to fetch logs:', e)
    }
  }, [threadId])

  // 轮询
  useEffect(() => {
    if (!threadId || !polling) return

    fetchWorkflow()
    fetchLogs()

    const interval = setInterval(() => {
      fetchWorkflow()
      fetchLogs()
    }, 1000)

    return () => clearInterval(interval)
  }, [threadId, polling, fetchWorkflow, fetchLogs])

  // 获取状态图标
  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed': return <CheckCircle2 className="h-5 w-5 text-green-500" />
      case 'running': return <Loader2 className="h-5 w-5 text-blue-500 animate-spin" />
      case 'failed': return <XCircle className="h-5 w-5 text-red-500" />
      default: return <Clock className="h-5 w-5 text-gray-400" />
    }
  }

  // 获取状态颜色
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'bg-green-500/10 border-green-500/50'
      case 'running': return 'bg-blue-500/10 border-blue-500/50'
      case 'failed': return 'bg-red-500/10 border-red-500/50'
      default: return 'bg-gray-500/10 border-gray-500/50'
    }
  }

  if (!threadId) {
    return (
      <div className="max-w-4xl mx-auto p-6">
        <Card>
          <CardContent className="p-8 text-center">
            <p className="text-muted-foreground">No workflow selected</p>
            <Button className="mt-4" onClick={() => router.push('/')}>
              Start New Analysis
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => router.push('/')}>
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <div>
            <h1 className="text-2xl font-bold">Workflow Monitor</h1>
            <p className="text-sm text-muted-foreground">Thread: {threadId.slice(0, 20)}...</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {polling && <Loader2 className="h-4 w-4 animate-spin text-blue-500" />}
          <Badge variant={workflow?.status === 'completed' ? 'success' : workflow?.status === 'failed' ? 'destructive' : 'default'}>
            {workflow?.status || 'loading'}
          </Badge>
        </div>
      </div>

      {/* Error */}
      {error && (
        <Card className="border-red-500">
          <CardContent className="p-4 text-red-500">
            Error: {error}
          </CardContent>
        </Card>
      )}

      {/* Progress */}
      {workflow && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex justify-between">
              <span>Progress</span>
              <span>{Math.round(workflow.progress)}%</span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Progress value={workflow.progress} className="h-2" />
          </CardContent>
        </Card>
      )}

      {/* Agents */}
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
                    <p className="text-xs text-muted-foreground capitalize">{status}</p>
                  </div>
                  {getStatusIcon(status)}
                </div>
                {state?.error && (
                  <p className="mt-2 text-xs text-red-500 truncate">{state.error}</p>
                )}
              </CardContent>
            </Card>
          )
        })}
      </div>

      {/* Logs */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center justify-between">
            <span>Execution Logs</span>
            <span className="text-muted-foreground font-normal">{logs.length} entries</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-1 max-h-64 overflow-y-auto font-mono text-xs bg-muted/30 p-3 rounded">
            {logs.length === 0 ? (
              <p className="text-muted-foreground text-center py-4">No logs yet</p>
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

      {/* Actions */}
      <div className="flex justify-center gap-4">
        <Button variant="outline" onClick={() => router.push('/')}>
          New Analysis
        </Button>
        {workflow?.status === 'completed' && (
          <Button onClick={() => router.push(`/result?thread_id=${threadId}`)}>
            View Results
          </Button>
        )}
      </div>
    </div>
  )
}

// Wrap with Suspense for useSearchParams
export default function MonitoringPageWrapper() {
  return (
    <Suspense fallback={
      <div className="max-w-5xl mx-auto p-6 flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
      </div>
    }>
      <MonitoringPage />
    </Suspense>
  )
}

'use client'

import { useState, useEffect, useCallback, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { cn, API } from '@/lib/utils'
import type { ReactProgressResponse } from '@/lib/utils'
import {
  Database, TrendingUp, BarChart3, MessageSquare, Shield, Brain, FileText,
  Loader2, CheckCircle2, XCircle, Clock, ArrowLeft, Wrench, Zap
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

const STEP_LABELS: Record<string, { label: string; color: string }> = {
  reasoning: { label: '推理中', color: 'bg-purple-500' },
  executing_tools: { label: '执行工具', color: 'bg-blue-500' },
  observing: { label: '观察结果', color: 'bg-cyan-500' },
  reflecting: { label: '反思决策', color: 'bg-amber-500' },
  completed: { label: '已完成', color: 'bg-green-500' },
  failed: { label: '失败', color: 'bg-red-500' },
  starting: { label: '启动中', color: 'bg-slate-500' },
}

/* ── ReAct Monitoring View ─────────────────────────────────────── */

function ReactMonitor({ threadId }: { threadId: string }) {
  const router = useRouter()
  const [progress, setProgress] = useState<ReactProgressResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [polling, setPolling] = useState(true)

  const fetchProgress = useCallback(async () => {
    try {
      const data = await API.getReactProgress(threadId)
      setProgress(data)
      setError(null)
      if (data.status === 'completed' || data.status === 'failed') {
        setPolling(false)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error')
    }
  }, [threadId])

  useEffect(() => {
    fetchProgress()
    if (!polling) return
    const interval = setInterval(fetchProgress, 2000)
    return () => clearInterval(interval)
  }, [threadId, polling, fetchProgress])

  const stepInfo = STEP_LABELS[progress?.current_step || 'starting'] || STEP_LABELS.starting
  const iterPct = progress ? Math.round((progress.iteration / progress.max_iterations) * 100) : 0

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => router.push('/')}>
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <div>
            <h1 className="text-2xl font-bold">ReAct Agent Monitor</h1>
            <p className="text-sm text-muted-foreground">Thread: {threadId.slice(0, 24)}...</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {polling && <Loader2 className="h-4 w-4 animate-spin text-blue-500" />}
          <Badge variant={progress?.status === 'completed' ? 'success' : progress?.status === 'failed' ? 'destructive' : 'default'}>
            {progress?.status === 'completed' ? '已完成' : progress?.status === 'failed' ? '失败' : '处理中'}
          </Badge>
        </div>
      </div>

      {error && (
        <Card className="border-red-500">
          <CardContent className="p-4 text-red-500">Error: {error}</CardContent>
        </Card>
      )}

      {/* Current Step */}
      {progress && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center justify-between">
              <span className="flex items-center gap-2">
                <Zap className="h-4 w-4" />
                当前状态
              </span>
              <div className="flex items-center gap-2">
                <span className="inline-block w-2 h-2 rounded-full animate-pulse" style={{ backgroundColor: stepInfo.color.replace('bg-', '') }} />
                <span>{stepInfo.label}</span>
              </div>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between text-sm text-muted-foreground">
              <span>Iteration {progress.iteration} / {progress.max_iterations}</span>
              <span>{iterPct}%</span>
            </div>
            <Progress value={iterPct} className="h-2" />
          </CardContent>
        </Card>
      )}

      {/* Tool Call Timeline */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center justify-between">
            <span className="flex items-center gap-2">
              <Wrench className="h-4 w-4" />
              工具调用记录
            </span>
            <Badge variant="outline">{progress?.tool_call_history.length || 0} 次调用</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!progress?.tool_call_history.length ? (
            <p className="text-center py-6 text-muted-foreground text-sm">等待工具调用...</p>
          ) : (
            <div className="space-y-2 max-h-80 overflow-y-auto">
              {progress.tool_call_history.map((tc, i) => (
                <div key={i} className="flex items-start gap-3 p-3 rounded-lg bg-muted/30 border">
                  <div className="flex items-center justify-center w-7 h-7 rounded-full bg-blue-100 text-blue-600 text-xs font-bold shrink-0">
                    {i + 1}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm font-medium text-blue-700">{tc.tool}</span>
                      <CheckCircle2 className="h-3.5 w-3.5 text-green-500 shrink-0" />
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground font-mono truncate">
                      {Object.entries(tc.args).map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`).join(', ')}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Tools Used Summary */}
      {progress && progress.tools_used.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">已使用工具</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {[...new Set(progress.tools_used)].map(tool => (
                <Badge key={tool} variant="outline" className="font-mono text-xs">
                  {tool}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Actions */}
      <div className="flex justify-center gap-4">
        <Button variant="outline" onClick={() => router.push('/')}>
          新建分析
        </Button>
        {progress?.status === 'completed' && (
          <Button onClick={() => router.push(`/result?thread_id=${threadId}&mode=react`)}>
            查看结果
          </Button>
        )}
      </div>
    </div>
  )
}

/* ── Pipeline Monitoring View (original) ───────────────────────── */

function PipelineMonitor({ threadId }: { threadId: string }) {
  const router = useRouter()
  const [workflow, setWorkflow] = useState<WorkflowState | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [error, setError] = useState<string | null>(null)
  const [polling, setPolling] = useState(true)

  const fetchWorkflow = useCallback(async () => {
    if (!threadId) return
    try {
      const res = await fetch(`${API_BASE}/monitor/workflow/${threadId}`)
      if (!res.ok) {
        if (res.status === 404) { setError('Workflow not found'); return }
        throw new Error(`HTTP ${res.status}`)
      }
      const data = await res.json()
      setWorkflow(data)
      setError(null)
      if (data.status === 'completed' || data.status === 'failed') setPolling(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error')
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
    const interval = setInterval(() => { fetchWorkflow(); fetchLogs() }, 1000)
    return () => clearInterval(interval)
  }, [threadId, polling, fetchWorkflow, fetchLogs])

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

      {error && (
        <Card className="border-red-500">
          <CardContent className="p-4 text-red-500">Error: {error}</CardContent>
        </Card>
      )}

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
                {state?.error && <p className="mt-2 text-xs text-red-500 truncate">{state.error}</p>}
              </CardContent>
            </Card>
          )
        })}
      </div>

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

      <div className="flex justify-center gap-4">
        <Button variant="outline" onClick={() => router.push('/')}>New Analysis</Button>
        {workflow?.status === 'completed' && (
          <Button onClick={() => router.push(`/result?thread_id=${threadId}`)}>View Results</Button>
        )}
      </div>
    </div>
  )
}

/* ── Main Page ─────────────────────────────────────────────────── */

function MonitoringPage() {
  const searchParams = useSearchParams()
  const threadId = searchParams.get('thread_id')
  const mode = searchParams.get('mode')

  const router = useRouter()

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

  if (mode === 'react') {
    return <ReactMonitor threadId={threadId} />
  }

  return <PipelineMonitor threadId={threadId} />
}

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

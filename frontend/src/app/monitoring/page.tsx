'use client'

import { useState, useEffect, useCallback, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { cn, API } from '@/lib/utils'
import { relativeTime } from '@/lib/format'
import { providerTone, type ProviderTone } from '@/lib/verdicts'
import type {
  ReactProgressResponse, DataSourceHealthResponse,
  SystemHealth, CircuitBreakersResponse, RetryStatsResponse, TimeoutStatsResponse,
} from '@/lib/utils'
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
  { key: 'research_synthesis', name: 'Research Synthesis', icon: Zap },
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
  running_agents?: string[]
  // Synthesized join annotation from the workflow status API; currently
  // "analysis_barrier" while the parallel analysis superstep has fully
  // settled but risk_assessment has not started. Null/absent otherwise.
  phase?: string | null
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
  const { health: dataSourceHealth, fetchHealth: fetchDataSourceHealth } = useDataSourceHealth()

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
    fetchDataSourceHealth()
    if (!polling) return
    const interval = setInterval(() => {
      fetchProgress()
      fetchDataSourceHealth()
    }, 2000)
    return () => clearInterval(interval)
  }, [threadId, polling, fetchProgress, fetchDataSourceHealth])

  useEffect(() => {
    if (progress?.status !== 'completed') return
    // Completed — give the final status one visible beat, then land on the
    // report. Failed runs stay here so the error remains inspectable.
    const redirect = setTimeout(
      () => router.push(`/result?thread_id=${threadId}&mode=react`),
      2000
    )
    return () => clearTimeout(redirect)
  }, [progress?.status, router, threadId])

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

      {/* Data-source health — global provider counters, not thread-scoped */}
      <DataSourceHealthPanel health={dataSourceHealth} />

      <AgentHealthPanel />

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

/* ── Data-source health panel ──────────────────────────────────── */

const TONE_DOT: Record<ProviderTone, string> = {
  healthy: 'bg-green-500',
  degraded: 'bg-amber-500',
  down: 'bg-red-500',
}

function useDataSourceHealth() {
  const [health, setHealth] = useState<DataSourceHealthResponse | null>(null)
  const fetchHealth = useCallback(async () => {
    try {
      setHealth(await API.getDataSourceHealth())
    } catch { /* keep the last snapshot; this panel is a side channel */ }
  }, [])
  return { health, fetchHealth }
}

function DataSourceHealthPanel({ health }: { health: DataSourceHealthResponse | null }) {
  const providers = Object.entries(health?.providers ?? {})
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center justify-between">
          <span className="flex items-center gap-2">
            <Database className="h-4 w-4" />
            数据源健康
          </span>
          <Badge variant="outline">{providers.length} 个源</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {providers.length === 0 ? (
          <p className="text-center py-4 text-sm text-muted-foreground">暂无记录</p>
        ) : (
          <div className="space-y-1">
            {providers.map(([name, stats]) => {
              const lastOk = relativeTime(stats.last_ok_at)
              return (
                <div key={name} className="py-1.5 border-b border-border/30 last:border-0">
                  <div className="flex items-center justify-between gap-3 text-xs">
                    <span className="flex items-center gap-2 min-w-0">
                      <span className={cn('inline-block w-2 h-2 rounded-full shrink-0', TONE_DOT[providerTone(stats)])} />
                      <span className="font-mono truncate">{name}</span>
                    </span>
                    <span className="flex items-center gap-1.5 shrink-0">
                      <span className="text-green-600">成功 {stats.ok}</span>
                      <span className="text-muted-foreground">·</span>
                      <span className="text-amber-600">兜底 {stats.fallback}</span>
                      <span className="text-muted-foreground">·</span>
                      <span className="text-red-500">失败 {stats.fail}</span>
                      {lastOk && (
                        <>
                          <span className="text-muted-foreground">·</span>
                          <span className="text-muted-foreground" title="最后成功时间">{lastOk}</span>
                        </>
                      )}
                    </span>
                  </div>
                  {stats.last_error && (
                    <p className="mt-1 text-xs text-red-500/80 truncate" title={stats.last_error}>
                      最近错误: {stats.last_error}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        )}
        <p className="pt-2 text-[10px] text-muted-foreground">进程内计数，重启后清零</p>
      </CardContent>
    </Card>
  )
}

/* ── Agent resilience panel ────────────────────────────────────── */

interface ResilienceSnapshot {
  health: SystemHealth
  breakers: CircuitBreakersResponse
  retry: RetryStatsResponse
  timeouts: TimeoutStatsResponse
}

// Self-contained 10s polling: these are process-level counters that do not
// depend on the selected workflow, and firing four monitoring endpoints every
// 1s (the workflow poll cadence) would be chatty. On any fetch error the last
// snapshot stays — this panel is a side channel, never the primary view.
function useAgentResilience() {
  const [snapshot, setSnapshot] = useState<ResilienceSnapshot | null>(null)
  const fetchSnapshot = useCallback(async () => {
    try {
      const [health, breakers, retry, timeouts] = await Promise.all([
        API.getHealth(),
        API.getCircuitBreakers(),
        API.getRetryStats(),
        API.getTimeoutStats(),
      ])
      setSnapshot({ health, breakers, retry, timeouts })
    } catch { /* keep the last snapshot; this panel is a side channel */ }
  }, [])
  return { snapshot, fetchSnapshot }
}

const BREAKER_STATE: Record<string, { label: string; cls: string }> = {
  CLOSED: { label: '关闭', cls: 'bg-green-500/10 border-green-500/30 text-green-600' },
  OPEN: { label: '打开', cls: 'bg-red-500/10 border-red-500/30 text-red-500' },
  HALF_OPEN: { label: '半开', cls: 'bg-amber-500/10 border-amber-500/30 text-amber-600' },
}

const ALERT_SEVERITY_CLS: Record<string, string> = {
  critical: 'text-red-500',
  high: 'text-red-500',
  medium: 'text-amber-600 dark:text-amber-400',
  low: 'text-muted-foreground',
}

function AgentHealthPanel() {
  const { snapshot, fetchSnapshot } = useAgentResilience()
  const [resetting, setResetting] = useState<string | null>(null)

  useEffect(() => {
    void fetchSnapshot()
    const interval = setInterval(() => void fetchSnapshot(), 10000)
    return () => clearInterval(interval)
  }, [fetchSnapshot])

  const onReset = async (name: string) => {
    setResetting(name)
    try {
      await API.resetCircuitBreaker(name)
      await fetchSnapshot()
    } catch { /* the next poll picks the breaker state back up */ }
    setResetting(null)
  }

  if (!snapshot) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Shield className="h-4 w-4" />
            Agent 运行健康
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-center py-4 text-sm text-muted-foreground">暂无数据</p>
          <p className="pt-2 text-[10px] text-muted-foreground">进程内计数，重启后清零</p>
        </CardContent>
      </Card>
    )
  }

  const { health, breakers, retry, timeouts } = snapshot
  const breakerEntries = Object.entries(breakers ?? {})
  const timeoutEntries = Object.entries(timeouts ?? {}).filter(([, s]) => s.total_calls > 0)
  const timingOut = timeoutEntries.filter(([, s]) => s.timeout_calls > 0)
  const unhealthySet = new Set(health.unhealthy_agents ?? [])

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center justify-between">
          <span className="flex items-center gap-2">
            <Shield className="h-4 w-4" />
            Agent 运行健康
          </span>
          <span className="flex items-center gap-2">
            {health.unhealthy_agents.length > 0 && (
              <Badge variant="destructive">{health.unhealthy_agents.length} 个异常</Badge>
            )}
            <Badge variant="outline">{health.total_agents} 个 Agent</Badge>
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          <div className="p-2 rounded-lg bg-muted/50">
            <div className="text-muted-foreground">总执行</div>
            <div className="text-base font-bold">{health.total_executions}</div>
          </div>
          <div className="p-2 rounded-lg bg-muted/50">
            <div className="text-muted-foreground">成功率</div>
            <div className="text-base font-bold">
              {(health.overall_success_rate * 100).toFixed(1)}%
            </div>
          </div>
          <div className="p-2 rounded-lg bg-muted/50">
            <div className="text-muted-foreground">平均健康分</div>
            <div className="text-base font-bold">{health.avg_health_score.toFixed(0)}</div>
          </div>
          <div className="p-2 rounded-lg bg-muted/50">
            <div className="text-muted-foreground">重试</div>
            <div className="text-base font-bold">{retry.total_retries}</div>
          </div>
        </div>

        {Object.keys(health.agents_health ?? {}).length > 0 && (
          <div className="space-y-1">
            {Object.entries(health.agents_health).map(([name, score]) => (
              <div
                key={name}
                className="flex items-center justify-between text-xs py-1 border-b border-border/30 last:border-0"
              >
                <span className="flex items-center gap-2 min-w-0">
                  <span
                    className={cn(
                      'inline-block w-2 h-2 rounded-full shrink-0',
                      unhealthySet.has(name) ? 'bg-red-500' : 'bg-green-500'
                    )}
                  />
                  <span className="font-mono truncate">{name}</span>
                </span>
                <span
                  className={cn(
                    'shrink-0',
                    unhealthySet.has(name) ? 'text-red-500 font-semibold' : 'text-muted-foreground'
                  )}
                >
                  健康分 {score.toFixed(0)}
                </span>
              </div>
            ))}
          </div>
        )}

        {breakerEntries.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs font-medium text-muted-foreground">熔断器</div>
            {breakerEntries.map(([name, cb]) => {
              const state = BREAKER_STATE[cb.state] ?? BREAKER_STATE.CLOSED
              return (
                <div
                  key={name}
                  className="flex items-center justify-between gap-3 text-xs py-1 border-b border-border/30 last:border-0"
                >
                  <span className="font-mono truncate min-w-0" title={name}>{name}</span>
                  <span className="flex items-center gap-2 shrink-0">
                    <span className="text-muted-foreground">
                      失败率 {(cb.failure_rate * 100).toFixed(0)}% · 打开 {cb.opened_count} 次
                    </span>
                    <span className={cn('px-2 py-0.5 rounded-full border', state.cls)}>
                      {state.label}
                    </span>
                    {cb.state !== 'CLOSED' && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-6 px-2 text-xs"
                        disabled={resetting === name}
                        onClick={() => void onReset(name)}
                      >
                        {resetting === name ? '重置中…' : '重置'}
                      </Button>
                    )}
                  </span>
                </div>
              )
            })}
          </div>
        )}

        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>
            重试 {retry.total_retries} 次 · 成功 {retry.successful_retries}
            {typeof retry.avg_attempts === 'number' && retry.total_retries > 0
              ? ` · 平均尝试 ${retry.avg_attempts.toFixed(1)}`
              : ''}
          </span>
          {timeoutEntries.length > 0 && (
            <span>
              超时 {timeoutEntries.reduce((s, [, t]) => s + t.timeout_calls, 0)} 次 /{' '}
              {timeoutEntries.reduce((s, [, t]) => s + t.total_calls, 0)} 次调用
            </span>
          )}
        </div>
        {timingOut.length > 0 && (
          <div className="space-y-1">
            {timingOut.map(([op, t]) => (
              <div key={op} className="flex items-center justify-between text-xs py-1">
                <span className="font-mono truncate">{op}</span>
                <span className="text-amber-600 dark:text-amber-400 shrink-0">
                  超时 {t.timeout_calls} 次 · 超时率 {(t.timeout_rate * 100).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        )}

        {health.active_alerts.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs font-medium text-muted-foreground">活跃告警</div>
            {health.active_alerts.map((a) => (
              <div key={a.alert_id} className="flex items-center justify-between gap-3 text-xs py-1">
                <span className="flex items-center gap-2 min-w-0">
                  <span className="font-mono text-muted-foreground shrink-0">{a.agent}</span>
                  <span
                    className={cn('truncate', ALERT_SEVERITY_CLS[a.severity] ?? '')}
                    title={a.message}
                  >
                    {a.message}
                  </span>
                </span>
                <span className="text-muted-foreground shrink-0">{relativeTime(a.timestamp)}</span>
              </div>
            ))}
          </div>
        )}

        <p className="pt-2 text-[10px] text-muted-foreground">进程内计数，重启后清零</p>
      </CardContent>
    </Card>
  )
}

/* ── Pipeline Monitoring View (original) ───────────────────────── */

function PipelineMonitor({ threadId }: { threadId: string }) {
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

      <DataSourceHealthPanel health={dataSourceHealth} />

      <AgentHealthPanel />

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

/* No workflow selected — the health panel is global (process-wide provider
 * counters), so it stays useful here. No other data flows on this branch,
 * so the panel drives its own lightweight 10s polling. */
function NoWorkflowSelected() {
  const router = useRouter()
  const { health: dataSourceHealth, fetchHealth: fetchDataSourceHealth } = useDataSourceHealth()

  useEffect(() => {
    fetchDataSourceHealth()
    const interval = setInterval(fetchDataSourceHealth, 10000)
    return () => clearInterval(interval)
  }, [fetchDataSourceHealth])

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      <Card>
        <CardContent className="p-8 text-center">
          <p className="text-muted-foreground">No workflow selected</p>
          <Button className="mt-4" onClick={() => router.push('/')}>
            Start New Analysis
          </Button>
        </CardContent>
      </Card>
      <DataSourceHealthPanel health={dataSourceHealth} />
      <AgentHealthPanel />
    </div>
  )
}

function MonitoringPage() {
  const searchParams = useSearchParams()
  const threadId = searchParams.get('thread_id')
  const mode = searchParams.get('mode')

  if (!threadId) {
    return <NoWorkflowSelected />
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

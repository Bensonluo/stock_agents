'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { API } from '@/lib/utils'
import type { ReactProgressResponse } from '@/lib/utils'
import { useDataSourceHealth } from './useDataSourceHealth'
import { DataSourceHealthPanel } from './DataSourceHealthPanel'
import { AgentHealthPanel } from './AgentHealthPanel'
import {
  Loader2, CheckCircle2, XCircle, ArrowLeft, Wrench, Zap, ChevronRight
} from 'lucide-react'

/* hex 必须是真实 CSS 颜色 —— 此前 'purple-500' 这类 Tailwind 类名片段
 * 被塞进 style.backgroundColor,不是合法颜色,圆点一直隐形(迭代 150 修复)。 */
const STEP_META: Record<string, { label: string; hex: string }> = {
  reasoning: { label: '推理中', hex: '#a855f7' },
  executing_tools: { label: '执行工具', hex: '#3b82f6' },
  observing: { label: '观察结果', hex: '#06b6d4' },
  reflecting: { label: '反思决策', hex: '#f59e0b' },
  completed: { label: '已完成', hex: '#22c55e' },
  failed: { label: '失败', hex: '#ef4444' },
  starting: { label: '启动中', hex: '#64748b' },
}

// ReAct 循环的展示顺序(推理→工具→观察→反思,随后回到推理)
const PIPELINE = ['starting', 'reasoning', 'executing_tools', 'observing', 'reflecting'] as const

const formatElapsed = (ms: number) => {
  const s = Math.floor(ms / 1000)
  return s >= 60 ? `${Math.floor(s / 60)}分${String(s % 60).padStart(2, '0')}秒` : `${s}秒`
}

export function ReactMonitor({ threadId }: { threadId: string }) {
  const router = useRouter()
  const [progress, setProgress] = useState<ReactProgressResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [polling, setPolling] = useState(true)
  const [now, setNow] = useState(() => Date.now())
  const timelineRef = useRef<HTMLDivElement>(null)
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
      setError(e instanceof Error ? e.message : '未知错误')
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

  // 真实耗时:以服务端 started_at 为准,完成后冻结在 completed_at
  useEffect(() => {
    if (!progress || progress.status !== 'processing') return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [progress, progress?.status])

  const elapsedMs = (() => {
    if (!progress?.started_at) return null
    const start = new Date(progress.started_at).getTime()
    if (Number.isNaN(start)) return null
    const end =
      progress.status !== 'processing' && progress.completed_at
        ? new Date(progress.completed_at).getTime()
        : now
    if (Number.isNaN(end)) return null
    return Math.max(0, end - start)
  })()

  // 新工具调用到达时,时间线自动滚到底部(流式日志体验)
  useEffect(() => {
    const el = timelineRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [progress?.tool_call_history.length])

  const stepInfo = STEP_META[progress?.current_step || 'starting'] || STEP_META.starting
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
            <h1 className="text-2xl font-bold">ReAct 智能体监控</h1>
            <p className="text-sm text-muted-foreground font-mono">线程 {threadId.slice(0, 24)}...</p>
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
          <CardContent className="p-4 text-red-500">错误：{error}</CardContent>
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
              <span className="flex items-center gap-2">
                <span className="inline-block w-2 h-2 rounded-full animate-pulse" style={{ backgroundColor: stepInfo.hex }} />
                <span>{stepInfo.label}</span>
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* ReAct 循环步骤管线 */}
            <div className="flex items-center gap-1 flex-wrap">
              {PIPELINE.map((step, idx) => {
                const meta = STEP_META[step]
                const active = progress.status === 'processing' && progress.current_step === step
                return (
                  <div key={step} className="flex items-center gap-1">
                    {idx > 0 && <ChevronRight className="h-3 w-3 text-slate-300" />}
                    <div
                      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs border transition-all duration-300 ${
                        active
                          ? 'text-white border-transparent shadow-sm'
                          : 'text-slate-500 border-slate-200 bg-white'
                      }`}
                      style={active ? { backgroundColor: meta.hex } : undefined}
                    >
                      {active && <span className="w-1.5 h-1.5 rounded-full bg-white/90 animate-pulse" />}
                      {meta.label}
                    </div>
                  </div>
                )
              })}
              <ChevronRight className="h-3 w-3 text-slate-300" />
              <div
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs border transition-colors ${
                  progress.status === 'completed'
                    ? 'text-white border-transparent bg-green-500'
                    : progress.status === 'failed'
                      ? 'text-white border-transparent bg-red-500'
                      : 'text-slate-400 border-slate-200 bg-white'
                }`}
              >
                {progress.status === 'completed' && <CheckCircle2 className="h-3 w-3" />}
                {progress.status === 'failed' && <XCircle className="h-3 w-3" />}
                {progress.status === 'completed' ? '完成' : progress.status === 'failed' ? '失败' : '完成'}
              </div>
            </div>
            <div className="flex items-center justify-between text-sm text-muted-foreground">
              <span>迭代 {progress.iteration} / {progress.max_iterations}</span>
              <span className="tabular-nums">
                {elapsedMs !== null ? `已运行 ${formatElapsed(elapsedMs)}` : '计时不可用'}
                {' · '}{iterPct}%
              </span>
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
            <div ref={timelineRef} className="space-y-2 max-h-80 overflow-y-auto">
              {progress.tool_call_history.map((tc, i) => {
                const failed = tc.status === 'error'
                return (
                  <div
                    key={i}
                    className="flex items-start gap-3 p-3 rounded-lg bg-muted/30 border animate-in fade-in slide-in-from-bottom-1 duration-300"
                  >
                    <div className={`flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold shrink-0 ${failed ? 'bg-red-100 text-red-600' : 'bg-blue-100 text-blue-600'}`}>
                      {i + 1}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`font-mono text-sm font-medium ${failed ? 'text-red-700' : 'text-blue-700'}`}>{tc.tool}</span>
                        {failed
                          ? <XCircle className="h-3.5 w-3.5 text-red-500 shrink-0" />
                          : <CheckCircle2 className="h-3.5 w-3.5 text-green-500 shrink-0" />}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground font-mono truncate">
                        {Object.entries(tc.args).map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`).join(', ')}
                      </div>
                    </div>
                  </div>
                )
              })}
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

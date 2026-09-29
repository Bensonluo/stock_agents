'use client'

import { useState, useEffect, useCallback } from 'react'
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
  Loader2, CheckCircle2, ArrowLeft, Wrench, Zap
} from 'lucide-react'

const STEP_LABELS: Record<string, { label: string; color: string }> = {
  reasoning: { label: '推理中', color: 'bg-purple-500' },
  executing_tools: { label: '执行工具', color: 'bg-blue-500' },
  observing: { label: '观察结果', color: 'bg-cyan-500' },
  reflecting: { label: '反思决策', color: 'bg-amber-500' },
  completed: { label: '已完成', color: 'bg-green-500' },
  failed: { label: '失败', color: 'bg-red-500' },
  starting: { label: '启动中', color: 'bg-slate-500' },
}

export function ReactMonitor({ threadId }: { threadId: string }) {
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

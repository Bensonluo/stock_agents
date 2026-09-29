'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn, API } from '@/lib/utils'
import { relativeTime } from '@/lib/format'
import { useAgentResilience } from './useAgentResilience'
import { Shield } from 'lucide-react'

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

export function AgentHealthPanel() {
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

'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { relativeTime } from '@/lib/format'
import { providerTone, type ProviderTone } from '@/lib/verdicts'
import type { DataSourceHealthResponse } from '@/lib/utils'
import { Database } from 'lucide-react'

const TONE_DOT: Record<ProviderTone, string> = {
  healthy: 'bg-green-500',
  degraded: 'bg-amber-500',
  down: 'bg-red-500',
}

export function DataSourceHealthPanel({ health }: { health: DataSourceHealthResponse | null }) {
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

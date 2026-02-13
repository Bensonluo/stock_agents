'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Activity, Zap, AlertTriangle, RefreshCw, Server } from 'lucide-react'
import { API, type SystemHealth, type CircuitBreakersResponse } from '@/lib/utils'

export function MonitoringDashboard() {
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [circuits, setCircuits] = useState<CircuitBreakersResponse | null>(null)
  const [retryStats, setRetryStats] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  const fetchData = async () => {
    setLoading(true)
    try {
      const [healthData, circuitsData, retryData] = await Promise.all([
        API.getHealth(),
        API.getCircuitBreakers(),
        API.getRetryStats().catch(() => null),
      ])
      setHealth(healthData)
      setCircuits(circuitsData)
      setRetryStats(retryData)
    } catch (err) {
      console.error('Failed to fetch monitoring data:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 10000) // Refresh every 10s
    return () => clearInterval(interval)
  }, [])

  const handleResetCircuit = async (name: string) => {
    try {
      await API.resetCircuitBreaker(name)
      fetchData()
    } catch (err) {
      console.error('Failed to reset circuit:', err)
    }
  }

  const getHealthColor = (score: number) => {
    if (score >= 80) return 'text-green-500'
    if (score >= 50) return 'text-yellow-500'
    return 'text-red-500'
  }

  const getCircuitBadge = (state: string) => {
    switch (state) {
      case 'CLOSED':
        return <Badge variant="success">Closed</Badge>
      case 'OPEN':
        return <Badge variant="destructive">Open</Badge>
      case 'HALF_OPEN':
        return <Badge variant="warning">Half-Open</Badge>
      default:
        return <Badge variant="outline">{state}</Badge>
    }
  }

  if (loading && !health) {
    return (
      <Card>
        <CardContent className="p-6">
          <div className="flex items-center justify-center">
            <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">System Monitoring</h2>
          <p className="text-muted-foreground">Real-time agent health and circuit breaker status</p>
        </div>
        <Button onClick={fetchData} size="sm" variant="outline">
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* System Overview */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server className="h-5 w-5" />
            System Overview
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="p-4 bg-muted/50 rounded-lg">
              <div className="text-sm text-muted-foreground">Status</div>
              <div className="text-2xl font-bold capitalize">{health?.status || 'Unknown'}</div>
            </div>
            <div className="p-4 bg-muted/50 rounded-lg">
              <div className="text-sm text-muted-foreground">Agents</div>
              <div className="text-2xl font-bold">{Object.keys(health?.agents || {}).length}</div>
            </div>
            <div className="p-4 bg-muted/50 rounded-lg">
              <div className="text-sm text-muted-foreground">Open Circuits</div>
              <div className="text-2xl font-bold">
                {Object.values(circuits || {}).filter(c => c.state === 'OPEN').length}
              </div>
            </div>
            <div className="p-4 bg-muted/50 rounded-lg">
              <div className="text-sm text-muted-foreground">Uptime</div>
              <div className="text-2xl font-bold">
                {health?.uptime ? Math.floor(health.uptime / 60) + 'm' : '-'}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Agent Health */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5" />
            Agent Health
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {health?.agents && Object.entries(health.agents).map(([name, data]) => (
              <div key={name} className="border rounded-lg p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={`text-2xl font-bold ${getHealthColor(data.health_score)}`}>
                      {data.health_score.toFixed(0)}
                    </div>
                    <div>
                      <div className="font-medium capitalize">{name.replace(/_/g, ' ')}</div>
                      <div className="text-sm text-muted-foreground">
                        {data.total_calls} calls • {data.successful_calls} success
                      </div>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm text-muted-foreground">Success Rate</div>
                    <div className="font-medium">{(data.success_rate * 100).toFixed(1)}%</div>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-4 text-sm">
                  <div>
                    <span className="text-muted-foreground">Avg Latency:</span>{' '}
                    {data.avg_latency?.toFixed(0) || '-'}ms
                  </div>
                  <div>
                    <span className="text-muted-foreground">P95 Latency:</span>{' '}
                    {data.p95_latency?.toFixed(0) || '-'}ms
                  </div>
                  <div>
                    <span className="text-muted-foreground">P99 Latency:</span>{' '}
                    {data.p99_latency?.toFixed(0) || '-'}ms
                  </div>
                </div>

                {data.last_error && (
                  <div className="text-xs text-destructive bg-destructive/10 p-2 rounded">
                    Last Error: {data.last_error}
                  </div>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Circuit Breakers */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Zap className="h-5 w-5" />
            Circuit Breakers
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {circuits && Object.entries(circuits).map(([name, data]) => (
              <div key={name} className="flex items-center justify-between border rounded-lg p-4">
                <div className="flex items-center gap-4">
                  {getCircuitBadge(data.state)}
                  <div>
                    <div className="font-medium capitalize">{name.replace(/_/g, ' ')}</div>
                    <div className="text-sm text-muted-foreground">
                      {data.failure_count} failures • {data.success_count} successes
                    </div>
                  </div>
                </div>
                {data.state === 'OPEN' && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleResetCircuit(name)}
                  >
                    Reset
                  </Button>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Retry Statistics */}
      {retryStats && Object.keys(retryStats).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5" />
              Retry Statistics
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="p-4 bg-muted/50 rounded-lg">
                <div className="text-sm text-muted-foreground">Total Retries</div>
                <div className="text-2xl font-bold">
                  {Object.values(retryStats).reduce((sum: number, s: any) => sum + (s.total_retries || 0), 0)}
                </div>
              </div>
              <div className="p-4 bg-muted/50 rounded-lg">
                <div className="text-sm text-muted-foreground">Successful Retries</div>
                <div className="text-2xl font-bold text-green-500">
                  {Object.values(retryStats).reduce((sum: number, s: any) => sum + (s.successful_retries || 0), 0)}
                </div>
              </div>
              <div className="p-4 bg-muted/50 rounded-lg">
                <div className="text-sm text-muted-foreground">Failed After Retries</div>
                <div className="text-2xl font-bold text-red-500">
                  {Object.values(retryStats).reduce((sum: number, s: any) => sum + (s.failed_retries || 0), 0)}
                </div>
              </div>
              <div className="p-4 bg-muted/50 rounded-lg">
                <div className="text-sm text-muted-foreground">Retry Rate</div>
                <div className="text-2xl font-bold">
                  {Object.values(retryStats).length > 0
                    ? (
                        Object.values(retryStats).reduce((sum: number, s: any) =>
                          sum + (s.retry_rate || 0), 0
                        ) / Object.values(retryStats).length * 100
                      ).toFixed(1)
                    : 0}%
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

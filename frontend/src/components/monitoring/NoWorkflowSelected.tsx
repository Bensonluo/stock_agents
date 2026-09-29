'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { useDataSourceHealth } from './useDataSourceHealth'
import { DataSourceHealthPanel } from './DataSourceHealthPanel'
import { AgentHealthPanel } from './AgentHealthPanel'

/* No workflow selected — the health panel is global (process-wide provider
 * counters), so it stays useful here. No other data flows on this branch,
 * so the panel drives its own lightweight 10s polling. */
export function NoWorkflowSelected() {
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

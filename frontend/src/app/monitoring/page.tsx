'use client'

import { useState, useCallback } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Card, CardContent } from '@/components/ui/card'
import { RealTimeMonitor } from '@/components/monitoring/RealTimeMonitor'
import { WorkflowTimeline, WorkflowTimelineCompact, type AgentNodeStatus } from '@/components/monitoring/WorkflowTimeline'
import { MonitoringDashboard } from '@/components/monitoring/MonitoringDashboard'
import { Button } from '@/components/ui/button'
import { RefreshCw, Wifi, WifiOff } from 'lucide-react'
import { useWebSocket } from '@/hooks/useWebSocket'

export default function MonitoringPage() {
  const [activeTab, setActiveTab] = useState('realtime')
  const [isRefreshing, setIsRefreshing] = useState(false)

  // WebSocket connection for real-time updates
  const { connected, connectionStatus, clearMessages } = useWebSocket()

  // Simulated workflow status - in a real implementation, this would come from the API or WebSocket
  const [workflowStatus, setWorkflowStatus] = useState<Record<string, AgentNodeStatus>>({
    data_collection: { status: 'pending' },
    technical_analysis: { status: 'pending' },
    sentiment_analysis: { status: 'pending' },
    fundamental_analysis: { status: 'pending' },
    risk_assessment: { status: 'pending' },
    decision_making: { status: 'pending' },
    report_generation: { status: 'pending' },
  })

  const [currentAgent, setCurrentAgent] = useState<string | undefined>(undefined)

  // Handle manual refresh
  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true)
    // Clear messages and trigger a refresh
    clearMessages()
    // In a real implementation, you'd fetch fresh data here
    setTimeout(() => setIsRefreshing(false), 500)
  }, [clearMessages])

  // Connection status indicator
  const ConnectionIndicator = () => (
    <div className="flex items-center gap-2">
      {connected ? (
        <div className="flex items-center gap-1.5 text-green-500 bg-green-500/10 px-3 py-1.5 rounded-full text-sm">
          <Wifi className="h-3.5 w-3.5" />
          <span>Connected</span>
        </div>
      ) : (
        <div className="flex items-center gap-1.5 text-muted-foreground bg-muted/50 px-3 py-1.5 rounded-full text-sm">
          <WifiOff className="h-3.5 w-3.5" />
          <span>
            {connectionStatus === 'connecting' ? 'Connecting...' : 'Disconnected'}
          </span>
        </div>
      )}
    </div>
  )

  return (
    <div className="max-w-7xl mx-auto p-4 md:p-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">System Monitoring</h1>
          <p className="text-muted-foreground mt-1">
            Real-time agent health, workflow status, and system metrics
          </p>
        </div>
        <div className="flex items-center gap-3">
          <ConnectionIndicator />
          <Button
            onClick={handleRefresh}
            size="sm"
            variant="outline"
            disabled={isRefreshing}
          >
            <RefreshCw className={`mr-2 h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Tabs for different views */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
        <TabsList className="grid w-full max-w-md grid-cols-2">
          <TabsTrigger value="realtime">Real-time View</TabsTrigger>
          <TabsTrigger value="historical">Historical Metrics</TabsTrigger>
        </TabsList>

        {/* Real-time View Tab */}
        <TabsContent value="realtime" className="space-y-6">
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
            {/* Main Real-Time Monitor - spans 2 columns on large screens */}
            <div className="xl:col-span-2">
              <RealTimeMonitor maxEvents={30} />
            </div>

            {/* Workflow Timeline - spans 1 column */}
            <div className="xl:col-span-1">
              <div className="sticky top-6 space-y-6">
                <Card>
                  <CardContent className="p-4">
                    <h3 className="text-sm font-semibold mb-4 flex items-center gap-2">
                      <span className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
                      Active Workflows
                    </h3>
                    <WorkflowTimelineCompact
                      workflowStatus={workflowStatus}
                      currentAgent={currentAgent}
                    />
                  </CardContent>
                </Card>

                {/* Connection Info Card */}
                <Card>
                  <CardContent className="p-4">
                    <h3 className="text-sm font-semibold mb-3">Connection Details</h3>
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Status:</span>
                        <span className={connected ? 'text-green-500' : 'text-muted-foreground'}>
                          {connectionStatus}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Mode:</span>
                        <span>WebSocket</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Update Rate:</span>
                        <span>Real-time</span>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </div>
            </div>
          </div>

          {/* Full Workflow Timeline at bottom */}
          <WorkflowTimeline
            workflowStatus={workflowStatus}
            currentAgent={currentAgent}
          />
        </TabsContent>

        {/* Historical Metrics Tab */}
        <TabsContent value="historical" className="space-y-6">
          <MonitoringDashboard />
        </TabsContent>
      </Tabs>
    </div>
  )
}

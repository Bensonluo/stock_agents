'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Loader2, CheckCircle2, XCircle, Clock } from 'lucide-react'
import { API } from '@/lib/utils'

interface WorkflowProgressProps {
  threadId: string | null
  onComplete: (result: any) => void
}

const AGENT_ORDER = [
  'data_collection',
  'technical_analysis',
  'fundamental_analysis',
  'sentiment_analysis',
  'risk_assessment',
  'decision_making',
  'report_generation',
]

const AGENT_NAMES: Record<string, string> = {
  data_collection: 'Data Collection',
  technical_analysis: 'Technical Analysis',
  fundamental_analysis: 'Fundamental Analysis',
  sentiment_analysis: 'Sentiment Analysis',
  risk_assessment: 'Risk Assessment',
  decision_making: 'Decision Making',
  report_generation: 'Report Generation',
}

export function WorkflowProgress({ threadId, onComplete }: WorkflowProgressProps) {
  const [status, setStatus] = useState<{
    current_step: number
    current_agent: string | null
    agent_status: Record<string, string>
    has_errors: boolean
    is_complete: boolean
  } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!threadId) return

    const pollStatus = async () => {
      try {
        const result = await API.getWorkflowStatus(threadId)
        setStatus(result)

        if (result.is_complete) {
          // Get the full result
          try {
            const fullResult = await API.getAnalysisResult(threadId)
            onComplete(fullResult)
          } catch {
            // Might still be processing
          }
        }
      } catch (err) {
        if (err instanceof Error && err.message.includes('404')) {
          setError('Workflow not found')
        } else {
          setError(err instanceof Error ? err.message : 'Failed to get status')
        }
      }
    }

    pollStatus()
    const interval = setInterval(pollStatus, 2000)

    return () => clearInterval(interval)
  }, [threadId, onComplete])

  if (!threadId) return null

  if (error) {
    return (
      <Card className="border-destructive">
        <CardContent className="p-6">
          <div className="flex items-center gap-2 text-destructive">
            <XCircle className="h-5 w-5" />
            <span>{error}</span>
          </div>
        </CardContent>
      </Card>
    )
  }

  if (!status) {
    return (
      <Card>
        <CardContent className="p-6">
          <div className="flex items-center justify-center gap-2">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Initializing workflow...</span>
          </div>
        </CardContent>
      </Card>
    )
  }

  const getStatusIcon = (agentStatus: string) => {
    switch (agentStatus) {
      case 'completed':
        return <CheckCircle2 className="h-4 w-4 text-green-500" />
      case 'running':
        return <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
      case 'failed':
        return <XCircle className="h-4 w-4 text-destructive" />
      default:
        return <Clock className="h-4 w-4 text-muted-foreground" />
    }
  }

  const getStatusBadge = (agentStatus: string) => {
    switch (agentStatus) {
      case 'completed':
        return <Badge variant="success">Completed</Badge>
      case 'running':
        return <Badge variant="default">Running</Badge>
      case 'failed':
        return <Badge variant="destructive">Failed</Badge>
      case 'skipped':
        return <Badge variant="outline">Skipped</Badge>
      default:
        return <Badge variant="outline">Pending</Badge>
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Workflow Progress</span>
          <Badge variant={status.is_complete ? 'success' : 'default'}>
            {status.is_complete ? 'Complete' : `Step ${status.current_step}/7`}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {AGENT_ORDER.map((agent) => {
            // Get status from agent_status, default to 'pending' if not present
            const agentStatus = status.agent_status[agent] || 'pending'
            const isCurrent = status.current_agent === agent

            // Check if this agent was part of the workflow (exists in agent_status)
            const agentExists = agent in status.agent_status
            const displayStatus = agentExists ? agentStatus : 'skipped'

            return (
              <div
                key={agent}
                className={`flex items-center justify-between p-3 rounded-lg border transition-colors ${
                  isCurrent ? 'border-primary bg-primary/5' : 'border-border'
                } ${!agentExists ? 'opacity-50' : ''}`}
              >
                <div className="flex items-center gap-3">
                  {getStatusIcon(displayStatus)}
                  <span className={isCurrent ? 'font-medium' : ''}>{AGENT_NAMES[agent]}</span>
                  {!agentExists && <span className="text-xs text-muted-foreground">(not in workflow path)</span>}
                </div>
                {getStatusBadge(displayStatus)}
              </div>
            )
          })}
        </div>

        {status.has_errors && (
          <div className="mt-4 p-3 bg-destructive/10 border border-destructive/20 rounded-lg">
            <p className="text-sm text-destructive">
              Some agents encountered errors. The workflow continues with available data.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

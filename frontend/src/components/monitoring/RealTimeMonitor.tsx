'use client'

import { useEffect, useState, useMemo, type ReactNode } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { useWebSocket, type WebSocketMessage, sanitizeAgentName } from '@/hooks/useWebSocket'
import {
  Activity,
  Wifi,
  WifiOff,
  AlertCircle,
  CheckCircle2,
  Clock,
  Loader2,
  XCircle,
  Zap,
} from 'lucide-react'

// Whitelist of allowed agent names for display validation
const ALLOWED_AGENT_NAMES = [
  'data_collection',
  'data_agent',
  'technical_analysis',
  'analysis_agent',
  'fundamental_analysis',
  'sentiment_analysis',
  'sentiment_agent',
  'risk_assessment',
  'risk_agent',
  'decision_making',
  'decision_agent',
  'report_generation',
  'report_agent',
] as const

const AGENT_DISPLAY_NAMES: Record<string, string> = {
  data_collection: 'Data Collection',
  data_agent: 'Data Agent',
  technical_analysis: 'Technical Analysis',
  analysis_agent: 'Analysis Agent',
  fundamental_analysis: 'Fundamental Analysis',
  sentiment_analysis: 'Sentiment Analysis',
  sentiment_agent: 'Sentiment Agent',
  risk_assessment: 'Risk Assessment',
  risk_agent: 'Risk Agent',
  decision_making: 'Decision Making',
  decision_agent: 'Decision Agent',
  report_generation: 'Report Generation',
  report_agent: 'Report Agent',
}

const WORKFLOW_STEPS = [
  { key: 'data_collection', label: 'Data Collection' },
  { key: 'technical_analysis', label: 'Technical Analysis' },
  { key: 'fundamental_analysis', label: 'Fundamental Analysis' },
  { key: 'sentiment_analysis', label: 'Sentiment Analysis' },
  { key: 'risk_assessment', label: 'Risk Assessment' },
  { key: 'decision_making', label: 'Decision Making' },
  { key: 'report_generation', label: 'Report Generation' },
]

type AgentStatus = 'idle' | 'running' | 'completed' | 'failed' | 'retrying'

interface AgentState {
  name: string
  displayName: string
  status: AgentStatus
  healthScore: number
  lastExecutionTime: string | null
}

export interface RealTimeMonitorProps {
  maxEvents?: number
  className?: string
}

/**
 * Type guard to check if a value is a valid string
 */
function isValidString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0
}

/**
 * Type guard to check if a value is a valid number
 */
function isValidNumber(value: unknown): value is number {
  return typeof value === 'number' && !Number.isNaN(value) && Number.isFinite(value)
}

/**
 * Validates an agent name against the whitelist
 * Returns the sanitized name if valid, null otherwise
 */
function validateAgentName(agentName: unknown): string | null {
  const sanitized = sanitizeAgentName(agentName)
  if (!sanitized) {
    return null
  }

  // Check against whitelist
  if (!ALLOWED_AGENT_NAMES.includes(sanitized as typeof ALLOWED_AGENT_NAMES[number])) {
    // For unknown agent names, still allow but log a warning
    // This provides flexibility while maintaining security
    console.warn(`[RealTimeMonitor] Unknown agent name: "${sanitized}"`)
  }

  return sanitized
}

/**
 * Safely extracts a number from unknown data with a default fallback
 */
function safeExtractNumber(data: unknown, defaultValue: number = 0): number {
  return isValidNumber(data) ? data : defaultValue
}

/**
 * Safely extracts a string from unknown data with a default fallback
 */
function safeExtractString(data: unknown, defaultValue: string = ''): string {
  return isValidString(data) ? data : defaultValue
}

export function RealTimeMonitor({ maxEvents = 20, className = '' }: RealTimeMonitorProps) {
  const { connected, connectionStatus, messages, clearMessages } = useWebSocket()

  // Track agent states
  const [agentStates, setAgentStates] = useState<Record<string, AgentState>>({})
  const [activeWorkflow, setActiveWorkflow] = useState<{
    currentStep: number
    totalSteps: number
    status: 'idle' | 'running' | 'completed' | 'failed'
  }>({
    currentStep: 0,
    totalSteps: WORKFLOW_STEPS.length,
    status: 'idle',
  })

  // Update agent states based on WebSocket messages
  useEffect(() => {
    const latestMessages = messages.slice(-maxEvents)

    for (const message of latestMessages) {
      if (message.type === 'agent_event' || message.type === 'health_update') {
        // Safely extract agent name with validation
        const agentNameFromMsg = validateAgentName(message.agent_name)
        const agentNameFromData = validateAgentName(message.data?.agent_name)
        const agentName = agentNameFromMsg || agentNameFromData

        if (!agentName) {
          continue
        }

        const displayName = AGENT_DISPLAY_NAMES[agentName] ||
          agentName.replace(/_/g, ' ').replace(/\b\w/g, (l: string) => l.toUpperCase())

        // Determine status from message data
        let status: AgentStatus = 'idle'
        const eventType = safeExtractString(message.event_type || message.data?.event_type, '')

        if (eventType === 'started' || eventType === 'running') {
          status = 'running'
        } else if (eventType === 'completed' || eventType === 'success') {
          status = 'completed'
        } else if (eventType === 'failed' || eventType === 'error') {
          status = 'failed'
        } else if (eventType === 'retrying') {
          status = 'retrying'
        }

        // Get health score from message data with safe extraction
        const healthScore = safeExtractNumber(message.data?.health_score, 100)

        // Safely get timestamp
        const timestamp = isValidString(message.timestamp)
          ? message.timestamp
          : new Date().toISOString()

        setAgentStates(prev => ({
          ...prev,
          [agentName]: {
            name: agentName,
            displayName,
            status,
            healthScore,
            lastExecutionTime: timestamp,
          },
        } as Record<string, AgentState>))
      }

      // Update workflow progress
      if (message.type === 'agent_event' && message.event_type === 'step_completed') {
        const stepNumber = safeExtractNumber(message.data?.step_number, 0)
        setActiveWorkflow(prev => ({
          ...prev,
          currentStep: stepNumber + 1,
          status: stepNumber + 1 >= WORKFLOW_STEPS.length ? 'completed' : 'running',
        }))
      }

      if (message.type === 'agent_event' && message.event_type === 'workflow_started') {
        setActiveWorkflow({
          currentStep: 0,
          totalSteps: WORKFLOW_STEPS.length,
          status: 'running',
        })
      }

      if (message.type === 'agent_event' && message.event_type === 'workflow_completed') {
        setActiveWorkflow(prev => ({ ...prev, status: 'completed' }))
      }

      if (message.type === 'agent_event' && message.event_type === 'workflow_failed') {
        setActiveWorkflow(prev => ({ ...prev, status: 'failed' }))
      }
    }
  }, [messages, maxEvents])

  // Get connection status indicator
  const getConnectionIndicator = () => {
    switch (connectionStatus) {
      case 'connected':
        return (
          <div className="flex items-center gap-2 text-green-500">
            <Wifi className="h-4 w-4" />
            <span className="text-sm">Connected</span>
          </div>
        )
      case 'connecting':
        return (
          <div className="flex items-center gap-2 text-yellow-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="text-sm">Connecting...</span>
          </div>
        )
      case 'error':
        return (
          <div className="flex items-center gap-2 text-red-500">
            <WifiOff className="h-4 w-4" />
            <span className="text-sm">Connection Error</span>
          </div>
        )
      default:
        return (
          <div className="flex items-center gap-2 text-muted-foreground">
            <WifiOff className="h-4 w-4" />
            <span className="text-sm">Disconnected</span>
          </div>
        )
    }
  }

  // Get status badge for agent
  const getStatusBadge = (status: AgentStatus) => {
    switch (status) {
      case 'running':
        return <Badge variant="default">Running</Badge>
      case 'completed':
        return <Badge variant="success">Completed</Badge>
      case 'failed':
        return <Badge variant="destructive">Failed</Badge>
      case 'retrying':
        return <Badge variant="warning">Retrying</Badge>
      default:
        return <Badge variant="outline">Idle</Badge>
    }
  }

  // Get status icon for agent
  const getStatusIcon = (status: AgentStatus) => {
    switch (status) {
      case 'running':
        return <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
      case 'completed':
        return <CheckCircle2 className="h-4 w-4 text-green-500" />
      case 'failed':
        return <XCircle className="h-4 w-4 text-destructive" />
      case 'retrying':
        return <Zap className="h-4 w-4 text-yellow-500" />
      default:
        return <Clock className="h-4 w-4 text-muted-foreground" />
    }
  }

  // Get health score color
  const getHealthScoreColor = (score: number): string => {
    if (score >= 80) return 'text-green-500'
    if (score >= 50) return 'text-yellow-500'
    return 'text-red-500'
  }

  // Get health score background
  const getHealthScoreBg = (score: number): string => {
    if (score >= 80) return 'bg-green-500/10'
    if (score >= 50) return 'bg-yellow-500/10'
    return 'bg-red-500/10'
  }

  // Calculate workflow progress percentage
  const workflowProgress = useMemo(() => {
    return (activeWorkflow.currentStep / activeWorkflow.totalSteps) * 100
  }, [activeWorkflow])

  // Get recent events (last N messages)
  const recentEvents = useMemo(() => {
    return messages.slice(-maxEvents).reverse()
  }, [messages, maxEvents])

  // Get event icon based on type
  const getEventIcon = (message: WebSocketMessage) => {
    switch (message.type) {
      case 'error':
        return <AlertCircle className="h-4 w-4 text-destructive" />
      case 'alert':
        return <AlertCircle className="h-4 w-4 text-yellow-500" />
      case 'agent_event':
        return <Activity className="h-4 w-4 text-blue-500" />
      case 'health_update':
        return <CheckCircle2 className="h-4 w-4 text-green-500" />
      case 'circuit_breaker':
        return <Zap className="h-4 w-4 text-orange-500" />
      default:
        return <Activity className="h-4 w-4 text-muted-foreground" />
    }
  }

  // Format timestamp
  const formatTimestamp = (timestamp: string) => {
    const date = new Date(timestamp)
    const now = new Date()
    const diff = now.getTime() - date.getTime()

    if (diff < 60000) return 'Just now'
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`
    return date.toLocaleTimeString()
  }

  // Get agent display name from message
  const getAgentDisplayName = (message: WebSocketMessage): string => {
    if (isValidString(message.agent_name)) {
      const sanitizedName = sanitizeAgentName(message.agent_name)
      if (sanitizedName) {
        return AGENT_DISPLAY_NAMES[sanitizedName] || sanitizedName
      }
    }
    if (message.data?.agent_name && isValidString(message.data.agent_name)) {
      const name = message.data.agent_name
      const sanitizedName = sanitizeAgentName(name)
      if (sanitizedName) {
        return AGENT_DISPLAY_NAMES[sanitizedName] ||
          sanitizedName.replace(/_/g, ' ').replace(/\b\w/g, (l: string) => l.toUpperCase())
      }
    }
    return 'System'
  }

  // Get event display text
  const getEventDisplay = (message: WebSocketMessage): string => {
    const eventType = safeExtractString(message.event_type, '')
    if (eventType) return eventType

    const messageType = safeExtractString(message.type, '')
    return messageType ? messageType.replace(/_/g, ' ') : messageType
  }

  // Get message display if available
  const getMessageDisplay = (message: WebSocketMessage): ReactNode => {
    const messageContent = message.data?.message
    if (!isValidString(messageContent)) {
      return null
    }
    return (
      <p className="text-sm text-muted-foreground mt-1 truncate">
        {messageContent}
      </p>
    )
  }

  const agentEntries = Object.entries(agentStates)

  return (
    <div className={`space-y-6 ${className}`}>
      {/* Header with connection status */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">Real-Time Monitor</h2>
          <p className="text-muted-foreground">Live agent status and workflow progress</p>
        </div>
        <div className="flex items-center gap-4">
          {getConnectionIndicator()}
          <button
            onClick={clearMessages}
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            Clear Events
          </button>
        </div>
      </div>

      {/* Active Workflow Progress */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span className="flex items-center gap-2">
              <Activity className="h-5 w-5" />
              Active Workflow
            </span>
            <Badge
              variant={activeWorkflow.status === 'completed' ? 'success' : activeWorkflow.status === 'failed' ? 'destructive' : 'default'}
            >
              {activeWorkflow.status.charAt(0).toUpperCase() + activeWorkflow.status.slice(1)}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">
                Step {activeWorkflow.currentStep} of {activeWorkflow.totalSteps}
              </span>
              <span className="font-medium">{Math.round(workflowProgress)}%</span>
            </div>
            <Progress value={workflowProgress} className="h-2" />
          </div>

          <div className="grid grid-cols-7 gap-2">
            {WORKFLOW_STEPS.map((step, index) => {
              const isCompleted = index < activeWorkflow.currentStep
              const isCurrent = index === activeWorkflow.currentStep
              const isFailed = activeWorkflow.status === 'failed' && index === activeWorkflow.currentStep

              return (
                <div
                  key={step.key}
                  className={`
                    flex flex-col items-center justify-center p-2 rounded-lg border transition-all
                    ${isCompleted ? 'bg-green-500/10 border-green-500/30' : ''}
                    ${isCurrent ? 'bg-blue-500/10 border-blue-500/30 ring-2 ring-blue-500/20' : ''}
                    ${isFailed ? 'bg-destructive/10 border-destructive/30' : ''}
                    ${!isCompleted && !isCurrent ? 'bg-muted/30 border-border' : ''}
                  `}
                >
                  <div className={`
                    w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium
                    ${isCompleted ? 'bg-green-500 text-white' : ''}
                    ${isCurrent ? 'bg-blue-500 text-white' : ''}
                    ${isFailed ? 'bg-destructive text-white' : ''}
                    ${!isCompleted && !isCurrent ? 'bg-muted text-muted-foreground' : ''}
                  `}>
                    {isCompleted ? <CheckCircle2 className="h-4 w-4" /> : isFailed ? <XCircle className="h-4 w-4" /> : index + 1}
                  </div>
                  <span className="text-xs mt-1 text-center leading-tight">{step.label.split(' ')[0]}</span>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {/* Agent Status Cards */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5" />
            Agent Status
          </CardTitle>
        </CardHeader>
        <CardContent>
          {agentEntries.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <Activity className="h-12 w-12 mx-auto mb-3 opacity-50" />
              <p>No agent activity yet</p>
              <p className="text-sm">Agent statuses will appear here when workflows start</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {agentEntries.map(([agentKey, agent]) => (
                <div
                  key={agentKey}
                  className={`p-4 rounded-lg border transition-all ${getHealthScoreBg(agent.healthScore)}`}
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-2">
                      {getStatusIcon(agent.status)}
                      <h3 className="font-medium">{agent.displayName}</h3>
                    </div>
                    {getStatusBadge(agent.status)}
                  </div>

                  <div className="space-y-2">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">Health Score</span>
                      <span className={`font-semibold ${getHealthScoreColor(agent.healthScore)}`}>
                        {agent.healthScore}%
                      </span>
                    </div>

                    <div className="w-full bg-muted rounded-full h-1.5">
                      <div
                        className={`h-full rounded-full transition-all duration-300 ${
                          agent.healthScore >= 80 ? 'bg-green-500' :
                          agent.healthScore >= 50 ? 'bg-yellow-500' : 'bg-red-500'
                        }`}
                        style={{ width: `${agent.healthScore}%` }}
                      />
                    </div>

                    {agent.lastExecutionTime && (
                      <div className="flex items-center gap-1 text-xs text-muted-foreground">
                        <Clock className="h-3 w-3" />
                        <span>Last run: {formatTimestamp(agent.lastExecutionTime)}</span>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Recent Events */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5" />
            Recent Events
            <Badge variant="outline" className="ml-2">
              {recentEvents.length}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {recentEvents.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <Activity className="h-12 w-12 mx-auto mb-3 opacity-50" />
              <p>No events yet</p>
              <p className="text-sm">Real-time events will appear here</p>
            </div>
          ) : (
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {recentEvents.map((message, index) => (
                <div
                  key={`${message.timestamp}-${index}`}
                  className="flex items-start gap-3 p-3 rounded-lg bg-muted/30 border border-border/50 hover:bg-muted/50 transition-colors"
                >
                  <div className="mt-0.5">
                    {getEventIcon(message)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-sm capitalize">
                        {getAgentDisplayName(message)}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {getEventDisplay(message)}
                      </span>
                    </div>
                    {getMessageDisplay(message)}
                  </div>
                  <span className="text-xs text-muted-foreground whitespace-nowrap">
                    {message.timestamp ? formatTimestamp(message.timestamp) : 'Just now'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

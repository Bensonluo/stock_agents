'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import {
  Database,
  TrendingUp,
  MessageSquare,
  BarChart3,
  Shield,
  Brain,
  FileText,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
} from 'lucide-react'
import { type ReactNode } from 'react'

// Type definitions
export type AgentStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface AgentNodeStatus {
  status: AgentStatus
  executionTime?: number // in seconds
  error?: string
}

export interface WorkflowTimelineProps {
  workflowStatus: Record<string, AgentNodeStatus>
  currentAgent?: string
  className?: string
}

// Agent configuration with icons and display names
const AGENTS = [
  {
    key: 'data_collection',
    name: 'Data Collection',
    icon: Database,
    description: 'Fetch market data',
  },
  {
    key: 'technical_analysis',
    name: 'Technical Analysis',
    icon: TrendingUp,
    description: 'Analyze price trends',
  },
  {
    key: 'sentiment_analysis',
    name: 'Sentiment Analysis',
    icon: MessageSquare,
    description: 'Analyze news sentiment',
  },
  {
    key: 'fundamental_analysis',
    name: 'Fundamental Analysis',
    icon: BarChart3,
    description: 'Evaluate fundamentals',
  },
  {
    key: 'risk_assessment',
    name: 'Risk Assessment',
    icon: Shield,
    description: 'Assess portfolio risk',
  },
  {
    key: 'decision_making',
    name: 'Decision Making',
    icon: Brain,
    description: 'Generate investment decisions',
  },
  {
    key: 'report_generation',
    name: 'Report Generation',
    icon: FileText,
    description: 'Create analysis report',
  },
] as const

// Status colors and styles
const getStatusConfig = (status: AgentStatus) => {
  switch (status) {
    case 'completed':
      return {
        bgColor: 'bg-green-500/10',
        borderColor: 'border-green-500/50',
        iconColor: 'text-green-500',
        badgeVariant: 'success' as const,
        label: 'Completed',
      }
    case 'running':
      return {
        bgColor: 'bg-blue-500/10',
        borderColor: 'border-blue-500/50',
        iconColor: 'text-blue-500',
        badgeVariant: 'default' as const,
        label: 'Running',
      }
    case 'failed':
      return {
        bgColor: 'bg-red-500/10',
        borderColor: 'border-red-500/50',
        iconColor: 'text-red-500',
        badgeVariant: 'destructive' as const,
        label: 'Failed',
      }
    default:
      return {
        bgColor: 'bg-muted/30',
        borderColor: 'border-muted',
        iconColor: 'text-muted-foreground',
        badgeVariant: 'outline' as const,
        label: 'Pending',
      }
  }
}

// Status icon component
const StatusIcon = ({ status }: { status: AgentStatus }) => {
  switch (status) {
    case 'completed':
      return <CheckCircle2 className="h-5 w-5" />
    case 'running':
      return <Loader2 className="h-5 w-5 animate-spin" />
    case 'failed':
      return <XCircle className="h-5 w-5" />
    default:
      return <Clock className="h-5 w-5" />
  }
}

// Connection line component
const ConnectionLine = ({
  isActive,
  isCompleted,
}: {
  isActive: boolean
  isCompleted: boolean
}) => {
  return (
    <div className="flex-1 h-0.5 relative overflow-hidden">
      <div
        className={cn(
          'absolute inset-0 transition-all duration-500 ease-in-out',
          isCompleted
            ? 'bg-green-500'
            : isActive
              ? 'bg-blue-500/50'
              : 'bg-muted'
        )}
      >
        {isActive && !isCompleted && (
          <div className="absolute inset-0 bg-gradient-to-r from-transparent via-blue-400 to-transparent animate-pulse" />
        )}
      </div>
    </div>
  )
}

// Individual agent node component
const AgentNode = ({
  agent,
  status,
  executionTime,
  isActive,
}: {
  agent: (typeof AGENTS)[number]
  status: AgentStatus
  executionTime?: number
  isActive: boolean
}) => {
  const config = getStatusConfig(status)
  const Icon = agent.icon

  return (
    <div className="flex flex-col items-center min-w-[100px] max-w-[140px]">
      {/* Icon and status */}
      <div
        className={cn(
          'relative flex items-center justify-center w-14 h-14 rounded-full border-2 transition-all duration-300',
          config.bgColor,
          config.borderColor,
          isActive && 'ring-4 ring-primary/20 shadow-lg shadow-primary/10'
        )}
      >
        <span className={cn(config.iconColor, 'transition-colors duration-300')}>
          {status === 'running' ? (
            <Loader2 className="h-6 w-6 animate-spin" />
          ) : status === 'completed' ? (
            <CheckCircle2 className="h-6 w-6" />
          ) : status === 'failed' ? (
            <XCircle className="h-6 w-6" />
          ) : (
            <Icon className="h-6 w-6" />
          )}
        </span>

        {/* Pulsing animation for running state */}
        {status === 'running' && (
          <span className="absolute inset-0 rounded-full border-2 border-blue-500 animate-ping opacity-75" />
        )}
      </div>

      {/* Agent info */}
      <div className="mt-3 text-center">
        <p className="text-sm font-medium truncate w-full">{agent.name}</p>
        <p className="text-xs text-muted-foreground truncate">{agent.description}</p>

        {/* Status badge */}
        <div className="mt-2">
          <Badge variant={config.badgeVariant} className="text-[10px] px-1.5 py-0">
            {config.label}
          </Badge>
        </div>

        {/* Execution time */}
        {executionTime !== undefined && status === 'completed' && (
          <p className="text-xs text-muted-foreground mt-1">
            {executionTime > 0 ? `${executionTime.toFixed(1)}s` : '< 0.1s'}
          </p>
        )}
      </div>
    </div>
  )
}

// Main timeline component
export function WorkflowTimeline({
  workflowStatus,
  currentAgent,
  className,
}: WorkflowTimelineProps) {
  // Find the index of the current agent
  const currentIndex = currentAgent
    ? AGENTS.findIndex((a) => a.key === currentAgent)
    : -1

  // Check if workflow is complete (all agents completed)
  const isComplete = AGENTS.every(
    (agent) => workflowStatus[agent.key]?.status === 'completed'
  )

  // Calculate overall progress
  const completedCount = AGENTS.filter(
    (agent) => workflowStatus[agent.key]?.status === 'completed'
  ).length
  const progressPercent = (completedCount / AGENTS.length) * 100

  return (
    <Card className={cn('overflow-hidden', className)}>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock className="h-5 w-5" />
            <span>Workflow Timeline</span>
          </div>
          <div className="flex items-center gap-3">
            {/* Progress indicator */}
            <div className="text-sm text-muted-foreground">
              {completedCount}/{AGENTS.length} steps
            </div>
            <Badge variant={isComplete ? 'success' : 'default'}>
              {isComplete ? 'Complete' : currentAgent ? 'In Progress' : 'Pending'}
            </Badge>
          </div>
        </CardTitle>

        {/* Progress bar */}
        <div className="mt-2">
          <div className="h-2 w-full bg-muted rounded-full overflow-hidden">
            <div
              className="h-full bg-primary transition-all duration-500 ease-out"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {/* Horizontal timeline */}
        <div className="relative">
          {/* Connection lines row */}
          <div className="absolute top-7 left-14 right-14 flex items-center">
            {AGENTS.slice(0, -1).map((agent, index) => {
              const nextAgentStatus = workflowStatus[AGENTS[index + 1].key]?.status
              const isLineActive = index <= currentIndex
              const isLineCompleted =
                workflowStatus[agent.key]?.status === 'completed' &&
                (nextAgentStatus === 'completed' ||
                  nextAgentStatus === 'running' ||
                  index < currentIndex)

              return (
                <ConnectionLine
                  key={`line-${agent.key}`}
                  isActive={isLineActive}
                  isCompleted={isLineCompleted}
                />
              )
            })}
          </div>

          {/* Agents row */}
          <div className="flex items-center justify-between relative z-10">
            {AGENTS.map((agent) => {
              const agentStatus = workflowStatus[agent.key]
              const status = agentStatus?.status || 'pending'
              const executionTime = agentStatus?.executionTime
              const isActive = agent.key === currentAgent

              return (
                <AgentNode
                  key={agent.key}
                  agent={agent}
                  status={status}
                  executionTime={executionTime}
                  isActive={isActive}
                />
              )
            })}
          </div>
        </div>

        {/* Legend */}
        <div className="mt-8 flex flex-wrap items-center justify-center gap-4 text-xs text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <Clock className="h-3.5 w-3.5" />
            <span>Pending</span>
          </div>
          <div className="flex items-center gap-1.5">
            <Loader2 className="h-3.5 w-3.5" />
            <span>Running</span>
          </div>
          <div className="flex items-center gap-1.5">
            <CheckCircle2 className="h-3.5 w-3.5" />
            <span>Completed</span>
          </div>
          <div className="flex items-center gap-1.5">
            <XCircle className="h-3.5 w-3.5" />
            <span>Failed</span>
          </div>
        </div>

        {/* Failed agents warning */}
        {Object.values(workflowStatus).some((s) => s.status === 'failed') && (
          <div className="mt-6 p-4 bg-destructive/10 border border-destructive/20 rounded-lg">
            <div className="flex items-start gap-2">
              <XCircle className="h-5 w-5 text-destructive flex-shrink-0 mt-0.5" />
              <div className="text-sm">
                <p className="font-medium text-destructive">Some agents failed</p>
                <p className="text-destructive/80 mt-1">
                  The workflow encountered errors. Check individual agent status for details.
                </p>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// Compact version for smaller displays
export function WorkflowTimelineCompact({
  workflowStatus,
  currentAgent,
  className,
}: WorkflowTimelineProps) {
  return (
    <Card className={cn('p-4', className)}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-medium">Workflow Progress</span>
        <span className="text-xs text-muted-foreground">
          {Object.values(workflowStatus).filter((s) => s.status === 'completed').length}/{AGENTS.length}
        </span>
      </div>

      {/* Compact horizontal bar with agent icons */}
      <div className="flex items-center gap-1">
        {AGENTS.map((agent) => {
          const status = workflowStatus[agent.key]?.status || 'pending'
          const Icon = agent.icon
          const config = getStatusConfig(status)

          return (
            <div
              key={agent.key}
              className={cn(
                'flex-1 h-2 rounded-sm transition-all duration-300',
                config.bgColor,
                status === 'completed' && 'bg-green-500'
              )}
              title={`${agent.name}: ${config.label}`}
            >
              {agent.key === currentAgent && (
                <div className="absolute inset-0 bg-blue-500 animate-pulse" />
              )}
            </div>
          )
        })}
      </div>

      {/* Agent status icons */}
      <div className="flex items-center justify-between mt-2">
        {AGENTS.map((agent) => {
          const status = workflowStatus[agent.key]?.status || 'pending'
          const Icon = agent.icon
          const config = getStatusConfig(status)

          return (
            <div key={agent.key} className="relative">
              <Icon
                className={cn(
                  'h-4 w-4 transition-colors duration-300',
                  config.iconColor
                )}
              />
              {status === 'running' && (
                <span className="absolute -top-1 -right-1 h-2 w-2 bg-blue-500 rounded-full animate-ping" />
              )}
            </div>
          )
        })}
      </div>
    </Card>
  )
}

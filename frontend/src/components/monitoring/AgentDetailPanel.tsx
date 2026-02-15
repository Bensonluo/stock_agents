'use client'

import React, { useEffect, useRef, useMemo, useCallback, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import {
  X,
  Clock,
  Activity,
  AlertCircle,
  CheckCircle2,
  Loader2,
  XCircle,
  Zap,
  FileText,
  Terminal,
  AlertTriangle,
  Info,
} from 'lucide-react'

// Type definitions
export type AgentPanelStatus = 'idle' | 'running' | 'completed' | 'failed' | 'retrying'

export interface AgentPanelInfo {
  name: string
  displayName: string
  status: AgentPanelStatus
  healthScore: number
  executionTime?: number
  startTime?: string
  endTime?: string
  error?: string
}

export interface AgentLogEntry {
  timestamp: string
  level: 'debug' | 'info' | 'warning' | 'error'
  message: string
  data?: Record<string, unknown>
}

export interface AgentDetailPanelProps {
  agent: AgentPanelInfo | null
  logs: AgentLogEntry[]
  onClose: () => void
  className?: string
}

// Agent display names mapping
const AGENT_DISPLAY_NAMES: Record<string, string> = {
  data_collection: 'Data Collection Agent',
  data_agent: 'Data Agent',
  technical_analysis: 'Technical Analysis Agent',
  analysis_agent: 'Analysis Agent',
  fundamental_analysis: 'Fundamental Analysis Agent',
  sentiment_analysis: 'Sentiment Analysis Agent',
  sentiment_agent: 'Sentiment Agent',
  risk_assessment: 'Risk Assessment Agent',
  risk_agent: 'Risk Agent',
  decision_making: 'Decision Making Agent',
  decision_agent: 'Decision Agent',
  report_generation: 'Report Generation Agent',
  report_agent: 'Report Agent',
}

// Status configuration
const getStatusConfig = (status: AgentPanelStatus) => {
  switch (status) {
    case 'completed':
      return {
        bgColor: 'bg-green-500/10',
        borderColor: 'border-green-500/50',
        iconColor: 'text-green-500',
        badgeVariant: 'success' as const,
        label: 'Completed',
        Icon: CheckCircle2,
      }
    case 'running':
      return {
        bgColor: 'bg-blue-500/10',
        borderColor: 'border-blue-500/50',
        iconColor: 'text-blue-500',
        badgeVariant: 'default' as const,
        label: 'Running',
        Icon: Loader2,
      }
    case 'failed':
      return {
        bgColor: 'bg-red-500/10',
        borderColor: 'border-red-500/50',
        iconColor: 'text-red-500',
        badgeVariant: 'destructive' as const,
        label: 'Failed',
        Icon: XCircle,
      }
    case 'retrying':
      return {
        bgColor: 'bg-yellow-500/10',
        borderColor: 'border-yellow-500/50',
        iconColor: 'text-yellow-500',
        badgeVariant: 'warning' as const,
        label: 'Retrying',
        Icon: Zap,
      }
    default:
      return {
        bgColor: 'bg-muted/30',
        borderColor: 'border-muted',
        iconColor: 'text-muted-foreground',
        badgeVariant: 'outline' as const,
        label: 'Idle',
        Icon: Clock,
      }
  }
}

// Log level configuration
const getLogLevelConfig = (level: AgentLogEntry['level']) => {
  switch (level) {
    case 'error':
      return {
        bgColor: 'bg-red-500/10',
        borderColor: 'border-red-500/30',
        iconColor: 'text-red-500',
        Icon: AlertCircle,
      }
    case 'warning':
      return {
        bgColor: 'bg-yellow-500/10',
        borderColor: 'border-yellow-500/30',
        iconColor: 'text-yellow-500',
        Icon: AlertTriangle,
      }
    case 'debug':
      return {
        bgColor: 'bg-slate-500/10',
        borderColor: 'border-slate-500/30',
        iconColor: 'text-slate-400',
        Icon: Terminal,
      }
    default:
      return {
        bgColor: 'bg-blue-500/10',
        borderColor: 'border-blue-500/30',
        iconColor: 'text-blue-400',
        Icon: Info,
      }
  }
}

// Health score color helper
const getHealthScoreColor = (score: number): string => {
  if (score >= 80) return 'text-green-500'
  if (score >= 50) return 'text-yellow-500'
  return 'text-red-500'
}

const getHealthScoreBg = (score: number): string => {
  if (score >= 80) return 'bg-green-500'
  if (score >= 50) return 'bg-yellow-500'
  return 'bg-red-500'
}

// Format timestamp for display
const formatTimestamp = (timestamp: string): string => {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

// Format execution time
const formatExecutionTime = (seconds: number | undefined): string => {
  if (seconds === undefined) return 'N/A'
  if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  return `${minutes}m ${remainingSeconds.toFixed(0)}s`
}

// Log entry component
const LogEntry = ({ log }: { log: AgentLogEntry }) => {
  const config = getLogLevelConfig(log.level)
  const Icon = config.Icon

  return (
    <div
      className={cn(
        'flex items-start gap-2 p-2 rounded-lg border text-sm',
        config.bgColor,
        config.borderColor
      )}
    >
      <Icon className={cn('h-4 w-4 mt-0.5 flex-shrink-0', config.iconColor)} />
      <div className="flex-1 min-w-0 overflow-hidden">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground font-mono">
            {formatTimestamp(log.timestamp)}
          </span>
          <span className={cn('text-xs font-medium uppercase', config.iconColor)}>
            {log.level}
          </span>
        </div>
        <p className="mt-1 text-foreground break-words">{log.message}</p>
        {log.data && Object.keys(log.data).length > 0 && (
          <pre className="mt-2 p-2 bg-muted/50 rounded text-xs overflow-x-auto">
            {JSON.stringify(log.data, null, 2)}
          </pre>
        )}
      </div>
    </div>
  )
}

// Empty state component
const EmptyState = () => (
  <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
    <Activity className="h-12 w-12 mb-3 opacity-50" />
    <p className="font-medium">No Agent Selected</p>
    <p className="text-sm mt-1">Click on a workflow node to view details</p>
  </div>
)

// Main AgentDetailPanel component
export function AgentDetailPanel({
  agent,
  logs,
  onClose,
  className,
}: AgentDetailPanelProps) {
  const logsContainerRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (logsContainerRef.current) {
      logsContainerRef.current.scrollTop = logsContainerRef.current.scrollHeight
    }
  }, [logs])

  // Get display name
  const displayName = useMemo(() => {
    if (!agent) return ''
    return AGENT_DISPLAY_NAMES[agent.name] || agent.displayName || agent.name
  }, [agent])

  // Get status configuration
  const statusConfig = useMemo(() => {
    return getStatusConfig(agent?.status || 'idle')
  }, [agent?.status])

  // Calculate log statistics
  const logStats = useMemo(() => {
    const stats = { error: 0, warning: 0, info: 0, debug: 0 }
    for (const log of logs) {
      stats[log.level]++
    }
    return stats
  }, [logs])

  // Panel is closed when agent is null
  if (!agent) {
    return (
      <div
        className={cn(
          'fixed right-0 top-0 h-full w-96 bg-background border-l shadow-2xl',
          'transform translate-x-full transition-transform duration-300 ease-in-out',
          className
        )}
      >
        <EmptyState />
      </div>
    )
  }

  return (
    <div
      className={cn(
        'fixed right-0 top-0 h-full w-96 bg-background border-l shadow-2xl z-50',
        'transform transition-transform duration-300 ease-in-out',
        'flex flex-col',
        className
      )}
    >
      {/* Header */}
      <div className={cn('flex items-center justify-between p-4 border-b', statusConfig.bgColor)}>
        <div className="flex items-center gap-3">
          <div
            className={cn(
              'flex items-center justify-center w-10 h-10 rounded-full border-2',
              statusConfig.bgColor,
              statusConfig.borderColor
            )}
          >
            <statusConfig.Icon
              className={cn(
                'h-5 w-5',
                statusConfig.iconColor,
                agent.status === 'running' && 'animate-spin'
              )}
            />
          </div>
          <div>
            <h2 className="font-semibold text-foreground">{displayName}</h2>
            <Badge variant={statusConfig.badgeVariant} className="mt-1">
              {statusConfig.label}
            </Badge>
          </div>
        </div>
        <Button variant="ghost" size="icon" onClick={onClose} className="hover:bg-muted">
          <X className="h-5 w-5" />
        </Button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {/* Agent Info Card */}
        <Card className="m-4">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Activity className="h-4 w-4" />
              Agent Information
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {/* Health Score */}
            <div>
              <div className="flex items-center justify-between text-sm mb-1">
                <span className="text-muted-foreground">Health Score</span>
                <span className={cn('font-semibold', getHealthScoreColor(agent.healthScore))}>
                  {agent.healthScore}%
                </span>
              </div>
              <div className="w-full bg-muted rounded-full h-2">
                <div
                  className={cn('h-full rounded-full transition-all', getHealthScoreBg(agent.healthScore))}
                  style={{ width: `${agent.healthScore}%` }}
                />
              </div>
            </div>

            {/* Execution Time */}
            {agent.executionTime !== undefined && (
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground flex items-center gap-1">
                  <Clock className="h-3.5 w-3.5" />
                  Execution Time
                </span>
                <span className="font-mono">{formatExecutionTime(agent.executionTime)}</span>
              </div>
            )}

            {/* Start Time */}
            {agent.startTime && (
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Started</span>
                <span className="font-mono text-xs">
                  {new Date(agent.startTime).toLocaleString()}
                </span>
              </div>
            )}

            {/* End Time */}
            {agent.endTime && (
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Completed</span>
                <span className="font-mono text-xs">
                  {new Date(agent.endTime).toLocaleString()}
                </span>
              </div>
            )}

            {/* Agent Name (technical) */}
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Agent ID</span>
              <code className="text-xs bg-muted px-2 py-0.5 rounded">{agent.name}</code>
            </div>
          </CardContent>
        </Card>

        {/* Error Section */}
        {agent.error && (
          <Card className="mx-4 mb-4 border-destructive/50 bg-destructive/5">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2 text-destructive">
                <AlertCircle className="h-4 w-4" />
                Error Details
              </CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="text-sm text-destructive/90 whitespace-pre-wrap bg-destructive/10 p-3 rounded-lg overflow-x-auto">
                {agent.error}
              </pre>
            </CardContent>
          </Card>
        )}

        {/* Logs Section */}
        <Card className="mx-4 mb-4">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center justify-between">
              <div className="flex items-center gap-2">
                <FileText className="h-4 w-4" />
                Execution Logs
              </div>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                {logStats.error > 0 && (
                  <span className="text-red-500">{logStats.error} errors</span>
                )}
                {logStats.warning > 0 && (
                  <span className="text-yellow-500">{logStats.warning} warnings</span>
                )}
                <span>{logs.length} total</span>
              </div>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {logs.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                <Terminal className="h-8 w-8 mx-auto mb-2 opacity-50" />
                <p className="text-sm">No logs available</p>
                <p className="text-xs mt-1">Logs will appear here during execution</p>
              </div>
            ) : (
              <div
                ref={logsContainerRef}
                className="space-y-2 max-h-80 overflow-y-auto pr-2"
              >
                {logs.map((log, index) => (
                  <LogEntry key={`${log.timestamp}-${index}`} log={log} />
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Footer with close button */}
      <div className="p-4 border-t bg-muted/30">
        <Button variant="outline" className="w-full" onClick={onClose}>
          <X className="h-4 w-4 mr-2" />
          Close Panel
        </Button>
      </div>
    </div>
  )
}

// Hook for managing panel state
export function useAgentDetailPanel() {
  const [selectedAgent, setSelectedAgent] = useState<AgentPanelInfo | null>(null)
  const [logs, setLogs] = useState<AgentLogEntry[]>([])

  const openPanel = useCallback((agent: AgentPanelInfo, agentLogs: AgentLogEntry[]) => {
    setSelectedAgent(agent)
    setLogs(agentLogs)
  }, [])

  const closePanel = useCallback(() => {
    setSelectedAgent(null)
    setLogs([])
  }, [])

  const updateLogs = useCallback((newLogs: AgentLogEntry[]) => {
    setLogs(newLogs)
  }, [])

  return {
    selectedAgent,
    logs,
    openPanel,
    closePanel,
    updateLogs,
    isOpen: selectedAgent !== null,
  }
}

'use client'

import { useMemo, useCallback } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import {
  Database,
  TrendingUp,
  BarChart3,
  MessageSquare,
  Shield,
  Brain,
  FileText,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
  GitBranch,
} from 'lucide-react'

// Workflow graph structure definition
export const WORKFLOW_GRAPH = {
  nodes: [
    { id: 'data_collection', name: 'Data Collection', row: 0, col: 1 },
    { id: 'technical_analysis', name: 'Technical Analysis', row: 1, col: 0 },
    { id: 'fundamental_analysis', name: 'Fundamental Analysis', row: 1, col: 1 },
    { id: 'sentiment_analysis', name: 'Sentiment Analysis', row: 1, col: 2 },
    { id: 'risk_assessment', name: 'Risk Assessment', row: 2, col: 1 },
    { id: 'decision_making', name: 'Decision Making', row: 3, col: 1 },
    { id: 'report_generation', name: 'Report Generation', row: 4, col: 1 },
  ],
  edges: [
    { from: 'data_collection', to: 'technical_analysis' },
    { from: 'data_collection', to: 'fundamental_analysis' },
    { from: 'data_collection', to: 'sentiment_analysis' },
    { from: 'technical_analysis', to: 'risk_assessment' },
    { from: 'fundamental_analysis', to: 'risk_assessment' },
    { from: 'sentiment_analysis', to: 'risk_assessment' },
    { from: 'risk_assessment', to: 'decision_making' },
    { from: 'decision_making', to: 'report_generation' },
  ],
} as const

// Type definitions
export type NodeStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface WorkflowNodeStatus {
  status: NodeStatus
  executionTime?: number
  error?: string
  startTime?: string
  endTime?: string
}

export interface WorkflowGraphProps {
  nodeStatuses: Record<string, WorkflowNodeStatus>
  onNodeClick?: (nodeId: string) => void
  selectedNodeId?: string | null
  className?: string
}

// Node icon mapping
const NODE_ICONS: Record<string, typeof Database> = {
  data_collection: Database,
  technical_analysis: TrendingUp,
  fundamental_analysis: BarChart3,
  sentiment_analysis: MessageSquare,
  risk_assessment: Shield,
  decision_making: Brain,
  report_generation: FileText,
}

// Status configuration
const getStatusConfig = (status: NodeStatus) => {
  switch (status) {
    case 'completed':
      return {
        bgColor: 'bg-green-500/10',
        borderColor: 'border-green-500/50',
        iconColor: 'text-green-500',
        badgeVariant: 'success' as const,
        label: 'Completed',
        ringColor: 'ring-green-500/20',
      }
    case 'running':
      return {
        bgColor: 'bg-blue-500/10',
        borderColor: 'border-blue-500/50',
        iconColor: 'text-blue-500',
        badgeVariant: 'default' as const,
        label: 'Running',
        ringColor: 'ring-blue-500/20',
      }
    case 'failed':
      return {
        bgColor: 'bg-red-500/10',
        borderColor: 'border-red-500/50',
        iconColor: 'text-red-500',
        badgeVariant: 'destructive' as const,
        label: 'Failed',
        ringColor: 'ring-red-500/20',
      }
    default:
      return {
        bgColor: 'bg-muted/30',
        borderColor: 'border-muted',
        iconColor: 'text-muted-foreground',
        badgeVariant: 'outline' as const,
        label: 'Pending',
        ringColor: 'ring-muted/20',
      }
  }
}

// Calculate grid dimensions
const getGridDimensions = () => {
  const maxRow = Math.max(...WORKFLOW_GRAPH.nodes.map((n) => n.row))
  const maxCol = Math.max(...WORKFLOW_GRAPH.nodes.map((n) => n.col))
  return { rows: maxRow + 1, cols: maxCol + 1 }
}

// Node component
const WorkflowNode = ({
  nodeId,
  name,
  status,
  executionTime,
  isSelected,
  onClick,
}: {
  nodeId: string
  name: string
  status: NodeStatus
  executionTime?: number
  isSelected: boolean
  onClick: () => void
}) => {
  const Icon = NODE_ICONS[nodeId] || Database
  const config = getStatusConfig(status)

  return (
    <button
      onClick={onClick}
      className={cn(
        'flex flex-col items-center justify-center p-3 rounded-xl border-2 transition-all duration-300 cursor-pointer',
        'hover:scale-105 hover:shadow-lg min-w-[100px] max-w-[140px]',
        config.bgColor,
        config.borderColor,
        isSelected && `ring-4 ${config.ringColor} shadow-lg`,
        status === 'running' && 'animate-pulse'
      )}
    >
      {/* Icon container */}
      <div
        className={cn(
          'relative flex items-center justify-center w-12 h-12 rounded-full border-2 transition-all',
          config.bgColor,
          config.borderColor
        )}
      >
        {status === 'running' ? (
          <Loader2 className={cn('h-6 w-6 animate-spin', config.iconColor)} />
        ) : status === 'completed' ? (
          <CheckCircle2 className={cn('h-6 w-6', config.iconColor)} />
        ) : status === 'failed' ? (
          <XCircle className={cn('h-6 w-6', config.iconColor)} />
        ) : (
          <Icon className={cn('h-6 w-6', config.iconColor)} />
        )}

        {/* Running animation ring */}
        {status === 'running' && (
          <span className="absolute inset-0 rounded-full border-2 border-blue-500 animate-ping opacity-50" />
        )}
      </div>

      {/* Node name */}
      <span className="mt-2 text-xs font-medium text-center leading-tight">
        {name}
      </span>

      {/* Status badge */}
      <Badge variant={config.badgeVariant} className="mt-1.5 text-[10px] px-1.5 py-0">
        {config.label}
      </Badge>

      {/* Execution time */}
      {executionTime !== undefined && status === 'completed' && (
        <span className="text-[10px] text-muted-foreground mt-1">
          {executionTime > 0 ? `${executionTime.toFixed(1)}s` : '< 0.1s'}
        </span>
      )}
    </button>
  )
}

// Edge connection line component (rendered as SVG overlay)
const EdgeConnections = ({
  nodePositions,
  nodeStatuses,
}: {
  nodePositions: Record<string, { x: number; y: number }>
  nodeStatuses: Record<string, WorkflowNodeStatus>
}) => {
  const edges = useMemo(() => {
    return WORKFLOW_GRAPH.edges.map((edge) => {
      const fromPos = nodePositions[edge.from]
      const toPos = nodePositions[edge.to]

      if (!fromPos || !toPos) return null

      const fromStatus = nodeStatuses[edge.from]?.status || 'pending'
      const toStatus = nodeStatuses[edge.to]?.status || 'pending'

      // Determine edge color based on statuses
      let edgeColor = 'hsl(var(--muted))'
      let isAnimated = false

      if (fromStatus === 'completed' && (toStatus === 'completed' || toStatus === 'running')) {
        edgeColor = '#22c55e' // green
      } else if (toStatus === 'running') {
        edgeColor = '#3b82f6' // blue
        isAnimated = true
      } else if (fromStatus === 'failed' || toStatus === 'failed') {
        edgeColor = '#ef4444' // red
      }

      // Calculate control points for curved lines
      const midY = (fromPos.y + toPos.y) / 2

      return {
        id: `${edge.from}-${edge.to}`,
        from: fromPos,
        to: toPos,
        midY,
        edgeColor,
        isAnimated,
      }
    }).filter(Boolean)
  }, [nodePositions, nodeStatuses])

  return (
    <svg className="absolute inset-0 pointer-events-none" style={{ width: '100%', height: '100%' }}>
      <defs>
        <marker
          id="arrowhead"
          markerWidth="10"
          markerHeight="7"
          refX="9"
          refY="3.5"
          orient="auto"
        >
          <polygon points="0 0, 10 3.5, 0 7" fill="hsl(var(--muted-foreground))" />
        </marker>
        <marker
          id="arrowhead-active"
          markerWidth="10"
          markerHeight="7"
          refX="9"
          refY="3.5"
          orient="auto"
        >
          <polygon points="0 0, 10 3.5, 0 7" fill="#3b82f6" />
        </marker>
        <marker
          id="arrowhead-complete"
          markerWidth="10"
          markerHeight="7"
          refX="9"
          refY="3.5"
          orient="auto"
        >
          <polygon points="0 0, 10 3.5, 0 7" fill="#22c55e" />
        </marker>
      </defs>

      {edges.map((edge) => {
        if (!edge) return null

        const markerId = edge.isAnimated
          ? 'arrowhead-active'
          : edge.edgeColor === '#22c55e'
            ? 'arrowhead-complete'
            : 'arrowhead'

        return (
          <g key={edge.id}>
            <path
              d={`M ${edge.from.x} ${edge.from.y} Q ${edge.from.x} ${edge.midY} ${edge.to.x} ${edge.to.y}`}
              fill="none"
              stroke={edge.edgeColor}
              strokeWidth="2"
              strokeDasharray={edge.isAnimated ? '5,5' : 'none'}
              markerEnd={`url(#${markerId})`}
              className={cn(edge.isAnimated && 'animate-dash')}
            />
            {edge.isAnimated && (
              <path
                d={`M ${edge.from.x} ${edge.from.y} Q ${edge.from.x} ${edge.midY} ${edge.to.x} ${edge.to.y}`}
                fill="none"
                stroke="rgba(59, 130, 246, 0.3)"
                strokeWidth="4"
                className="animate-pulse"
              />
            )}
          </g>
        )
      })}
    </svg>
  )
}

// Main WorkflowGraph component
export function WorkflowGraph({
  nodeStatuses,
  onNodeClick,
  selectedNodeId,
  className,
}: WorkflowGraphProps) {
  const { rows, cols } = getGridDimensions()

  // Handle node click
  const handleNodeClick = useCallback(
    (nodeId: string) => {
      onNodeClick?.(nodeId)
    },
    [onNodeClick]
  )

  // Calculate node positions for edge drawing
  const nodePositions = useMemo(() => {
    const positions: Record<string, { x: number; y: number }> = {}
    const cellWidth = 160 // Approximate cell width
    const cellHeight = 120 // Approximate cell height

    WORKFLOW_GRAPH.nodes.forEach((node) => {
      positions[node.id] = {
        x: node.col * cellWidth + cellWidth / 2,
        y: node.row * cellHeight + cellHeight / 2,
      }
    })

    return positions
  }, [])

  // Create grid layout
  const grid: Array<Array<typeof WORKFLOW_GRAPH.nodes[number] | null>> = useMemo(() => {
    const gridArray: Array<Array<typeof WORKFLOW_GRAPH.nodes[number] | null>> = []

    for (let row = 0; row < rows; row++) {
      gridArray[row] = []
      for (let col = 0; col < cols; col++) {
        const node = WORKFLOW_GRAPH.nodes.find((n) => n.row === row && n.col === col)
        gridArray[row][col] = node || null
      }
    }

    return gridArray
  }, [rows, cols])

  // Calculate overall progress
  const progress = useMemo(() => {
    const total = WORKFLOW_GRAPH.nodes.length
    const completed = WORKFLOW_GRAPH.nodes.filter(
      (node) => nodeStatuses[node.id]?.status === 'completed'
    ).length
    return { completed, total, percent: (completed / total) * 100 }
  }, [nodeStatuses])

  // Check if workflow has failed
  const hasFailed = useMemo(() => {
    return Object.values(nodeStatuses).some((s) => s.status === 'failed')
  }, [nodeStatuses])

  // Get currently running nodes
  const runningNodes = useMemo(() => {
    return WORKFLOW_GRAPH.nodes.filter(
      (node) => nodeStatuses[node.id]?.status === 'running'
    )
  }, [nodeStatuses])

  return (
    <Card className={cn('overflow-hidden', className)}>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <GitBranch className="h-5 w-5" />
            <span>Workflow Graph</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground">
              {progress.completed}/{progress.total} nodes
            </span>
            <Badge variant={hasFailed ? 'destructive' : progress.completed === progress.total ? 'success' : 'default'}>
              {hasFailed ? 'Failed' : progress.completed === progress.total ? 'Complete' : 'In Progress'}
            </Badge>
          </div>
        </CardTitle>

        {/* Progress bar */}
        <div className="mt-2">
          <div className="h-2 w-full bg-muted rounded-full overflow-hidden">
            <div
              className={cn(
                'h-full transition-all duration-500 ease-out',
                hasFailed ? 'bg-red-500' : 'bg-green-500'
              )}
              style={{ width: `${progress.percent}%` }}
            />
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {/* Parallel execution indicator */}
        {runningNodes.length > 1 && (
          <div className="mb-4 p-3 bg-blue-500/10 border border-blue-500/20 rounded-lg">
            <div className="flex items-center gap-2 text-blue-600">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span className="text-sm font-medium">
                Parallel execution: {runningNodes.length} agents running simultaneously
              </span>
            </div>
          </div>
        )}

        {/* Workflow graph grid */}
        <div className="relative">
          {/* SVG edge connections layer */}
          <div className="absolute inset-0" style={{ minWidth: cols * 160, minHeight: rows * 120 }}>
            <EdgeConnections nodePositions={nodePositions} nodeStatuses={nodeStatuses} />
          </div>

          {/* Grid of nodes */}
          <div
            className="relative z-10 grid gap-4"
            style={{
              gridTemplateRows: `repeat(${rows}, minmax(100px, auto))`,
              gridTemplateColumns: `repeat(${cols}, minmax(140px, 1fr))`,
            }}
          >
            {grid.map((row, rowIndex) =>
              row.map((node, colIndex) => {
                if (!node) {
                  return <div key={`empty-${rowIndex}-${colIndex}`} className="flex items-center justify-center" />
                }

                const nodeStatus = nodeStatuses[node.id]
                const status = nodeStatus?.status || 'pending'
                const executionTime = nodeStatus?.executionTime
                const isSelected = selectedNodeId === node.id

                return (
                  <div key={node.id} className="flex items-center justify-center">
                    <WorkflowNode
                      nodeId={node.id}
                      name={node.name}
                      status={status}
                      executionTime={executionTime}
                      isSelected={isSelected}
                      onClick={() => handleNodeClick(node.id)}
                    />
                  </div>
                )
              })
            )}
          </div>
        </div>

        {/* Legend */}
        <div className="mt-6 flex flex-wrap items-center justify-center gap-4 text-xs text-muted-foreground">
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
          <div className="flex items-center gap-1.5">
            <GitBranch className="h-3.5 w-3.5" />
            <span>Parallel Branch</span>
          </div>
        </div>

        {/* Failed nodes warning */}
        {hasFailed && (
          <div className="mt-4 p-4 bg-destructive/10 border border-destructive/20 rounded-lg">
            <div className="flex items-start gap-2">
              <XCircle className="h-5 w-5 text-destructive flex-shrink-0 mt-0.5" />
              <div className="text-sm">
                <p className="font-medium text-destructive">Workflow Error</p>
                <p className="text-destructive/80 mt-1">
                  One or more agents failed. Click on a failed node to see error details.
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
export function WorkflowGraphCompact({
  nodeStatuses,
  className,
}: Omit<WorkflowGraphProps, 'onNodeClick' | 'selectedNodeId'>) {
  const progress = useMemo(() => {
    const total = WORKFLOW_GRAPH.nodes.length
    const completed = WORKFLOW_GRAPH.nodes.filter(
      (node) => nodeStatuses[node.id]?.status === 'completed'
    ).length
    return { completed, total, percent: (completed / total) * 100 }
  }, [nodeStatuses])

  return (
    <Card className={cn('p-4', className)}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <GitBranch className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">Workflow Progress</span>
        </div>
        <span className="text-xs text-muted-foreground">
          {progress.completed}/{progress.total}
        </span>
      </div>

      {/* Compact grid of status indicators */}
      <div className="grid grid-cols-7 gap-1">
        {WORKFLOW_GRAPH.nodes.map((node) => {
          const status = nodeStatuses[node.id]?.status || 'pending'
          const config = getStatusConfig(status)
          const Icon = NODE_ICONS[node.id] || Database

          return (
            <div
              key={node.id}
              className={cn(
                'flex flex-col items-center justify-center p-2 rounded-lg transition-all',
                config.bgColor,
                status === 'running' && 'animate-pulse'
              )}
              title={`${node.name}: ${config.label}`}
            >
              <Icon className={cn('h-4 w-4', config.iconColor)} />
              {status === 'running' && (
                <span className="absolute -top-1 -right-1 h-2 w-2 bg-blue-500 rounded-full animate-ping" />
              )}
            </div>
          )
        })}
      </div>

      {/* Progress bar */}
      <div className="mt-3 h-1.5 bg-muted rounded-full overflow-hidden">
        <div
          className="h-full bg-green-500 transition-all duration-500"
          style={{ width: `${progress.percent}%` }}
        />
      </div>
    </Card>
  )
}

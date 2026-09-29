// Shared state shapes for the monitoring views -- mirrors the /api/monitor
// workflow status payloads (app/monitoring/workflow_status.py).

export interface AgentState {
  name: string
  status: string
  started_at?: string
  completed_at?: string
  error?: string
}

export interface WorkflowState {
  thread_id: string
  status: string
  agents: Record<string, AgentState>
  current_agent: string | null
  running_agents?: string[]
  // Synthesized join annotation from the workflow status API; currently
  // "analysis_barrier" while the parallel analysis superstep has fully
  // settled but risk_assessment has not started. Null/absent otherwise.
  phase?: string | null
  progress: number
  updated_at: string
}

export interface LogEntry {
  timestamp: string
  agent: string
  level: string
  message: string
}

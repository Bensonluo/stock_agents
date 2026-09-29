'use client'

import { useCallback, useState } from 'react'
import { API } from '@/lib/utils'
import type {
  SystemHealth, CircuitBreakersResponse, RetryStatsResponse, TimeoutStatsResponse,
} from '@/lib/utils'

export interface ResilienceSnapshot {
  health: SystemHealth
  breakers: CircuitBreakersResponse
  retry: RetryStatsResponse
  timeouts: TimeoutStatsResponse
}

// Self-contained 10s polling: these are process-level counters that do not
// depend on the selected workflow, and firing four monitoring endpoints every
// 1s (the workflow poll cadence) would be chatty. On any fetch error the last
// snapshot stays — this panel is a side channel, never the primary view.
export function useAgentResilience() {
  const [snapshot, setSnapshot] = useState<ResilienceSnapshot | null>(null)
  const fetchSnapshot = useCallback(async () => {
    try {
      const [health, breakers, retry, timeouts] = await Promise.all([
        API.getHealth(),
        API.getCircuitBreakers(),
        API.getRetryStats(),
        API.getTimeoutStats(),
      ])
      setSnapshot({ health, breakers, retry, timeouts })
    } catch { /* keep the last snapshot; this panel is a side channel */ }
  }, [])
  return { snapshot, fetchSnapshot }
}

'use client'

import { useCallback, useState } from 'react'
import { API } from '@/lib/utils'
import type { DataSourceHealthResponse } from '@/lib/utils'

export function useDataSourceHealth() {
  const [health, setHealth] = useState<DataSourceHealthResponse | null>(null)
  const fetchHealth = useCallback(async () => {
    try {
      setHealth(await API.getDataSourceHealth())
    } catch { /* keep the last snapshot; this panel is a side channel */ }
  }, [])
  return { health, fetchHealth }
}

'use client'

import { Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import { ReactMonitor } from '@/components/monitoring/ReactMonitor'
import { PipelineMonitor } from '@/components/monitoring/PipelineMonitor'
import { NoWorkflowSelected } from '@/components/monitoring/NoWorkflowSelected'
import { Loader2 } from 'lucide-react'

function MonitoringPage() {
  const searchParams = useSearchParams()
  const threadId = searchParams.get('thread_id')
  const mode = searchParams.get('mode')

  if (!threadId) {
    return <NoWorkflowSelected />
  }

  if (mode === 'react') {
    return <ReactMonitor threadId={threadId} />
  }

  return <PipelineMonitor threadId={threadId} />
}

export default function MonitoringPageWrapper() {
  return (
    <Suspense fallback={
      <div className="max-w-5xl mx-auto p-6 flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
      </div>
    }>
      <MonitoringPage />
    </Suspense>
  )
}

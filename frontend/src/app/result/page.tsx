'use client'

import { Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import { ReactResultPage } from '@/components/result/ReactResultPage'
import { PipelineResultPage } from '@/components/result/PipelineResultPage'
import { Loader2 } from 'lucide-react'

function ResultPage() {
  const searchParams = useSearchParams()
  const threadId = searchParams.get('thread_id')
  const mode = searchParams.get('mode')

  if (mode === 'react' && threadId) {
    return <ReactResultPage threadId={threadId} />
  }

  return <PipelineResultPage threadId={threadId} />
}

export default function ResultPageWrapper() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white flex items-center justify-center">
        <Loader2 className="h-10 w-10 animate-spin text-blue-500" />
      </div>
    }>
      <ResultPage />
    </Suspense>
  )
}

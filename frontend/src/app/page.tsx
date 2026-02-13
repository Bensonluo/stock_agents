'use client'

import { useState } from 'react'
import { AnalysisForm } from '@/components/analysis/AnalysisForm'
import { WorkflowProgress } from '@/components/analysis/WorkflowProgress'
import { AnalysisResult } from '@/components/analysis/AnalysisResult'

export default function HomePage() {
  const [threadId, setThreadId] = useState<string | null>(null)
  const [result, setResult] = useState<any>(null)

  const handleAnalysisStart = (newThreadId: string) => {
    setThreadId(newThreadId)
    setResult(null)
  }

  const handleComplete = (analysisResult: any) => {
    setResult(analysisResult)
  }

  const handleNewAnalysis = () => {
    setThreadId(null)
    setResult(null)
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="text-center space-y-2 mb-8">
        <h1 className="text-3xl font-bold">Stock Analysis</h1>
        <p className="text-muted-foreground">
          Run AI-powered multi-agent analysis on any stock with technical, fundamental, and sentiment insights
        </p>
      </div>

      {!threadId && !result && (
        <AnalysisForm onAnalysisStart={handleAnalysisStart} />
      )}

      {threadId && !result && (
        <>
          <WorkflowProgress threadId={threadId} onComplete={handleComplete} />
          <div className="flex justify-center">
            <button
              onClick={handleNewAnalysis}
              className="text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              Start New Analysis
            </button>
          </div>
        </>
      )}

      {result && (
        <>
          <AnalysisResult result={result} />
          <div className="flex justify-center">
            <button
              onClick={handleNewAnalysis}
              className="text-sm text-primary hover:underline"
            >
              Run Another Analysis
            </button>
          </div>
        </>
      )}
    </div>
  )
}

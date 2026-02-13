'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Loader2, TrendingUp } from 'lucide-react'
import { API, type AnalysisRequest } from '@/lib/utils'

interface AnalysisFormProps {
  onAnalysisStart: (threadId: string) => void
}

export function AnalysisForm({ onAnalysisStart }: AnalysisFormProps) {
  const [symbols, setSymbols] = useState('AAPL')
  const [query, setQuery] = useState('Analyze this stock for investment potential')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)

    const symbolList = symbols.split(',').map(s => s.trim().toUpperCase()).filter(s => s)

    if (symbolList.length === 0) {
      setError('Please enter at least one stock symbol')
      setLoading(false)
      return
    }

    // Validate symbols before sending
    const invalidSymbols = symbolList.filter(s => {
      // US stocks: 1-5 letters
      // Chinese stocks: 6 digits
      // HK stocks: 4-5 digits + .HK
      const usStock = /^[A-Z]{1,5}$/.test(s)
      const cnStock = /^\d{6}$/.test(s)
      const hkStock = /^\d{4,5}\.HK$/.test(s)
      return !usStock && !cnStock && !hkStock
    })

    if (invalidSymbols.length > 0) {
      setError(`Invalid stock symbols: ${invalidSymbols.join(', ')}. Use stock symbols like AAPL, TSLA, 3690.HK, or 600519`)
      setLoading(false)
      return
    }

    try {
      const request: AnalysisRequest = {
        query,
        symbols: symbolList,
        max_retries: 3,
        timeout_per_agent: 300,
        parallel_execution: true,
      }

      const response = await API.analyze(request)
      onAnalysisStart(response.thread_id)
    } catch (err) {
      console.error('Analysis error:', err)
      const errorMessage = err instanceof Error ? err.message : 'Failed to start analysis'
      setError(errorMessage)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <TrendingUp className="h-5 w-5" />
          Stock Analysis
        </CardTitle>
        <CardDescription>
          Run multi-agent analysis on stocks with technical, fundamental, and sentiment analysis
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="symbols">Stock Symbols (comma-separated)</Label>
            <Input
              id="symbols"
              placeholder="AAPL, TSLA, 3690.HK (Meituan), 600519"
              value={symbols}
              onChange={(e) => setSymbols(e.target.value)}
              disabled={loading}
            />
            <p className="text-xs text-muted-foreground">
              Use US stock symbols (AAPL), Chinese stocks (600519), or HK stocks (3690.HK)
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="query">Analysis Query</Label>
            <Textarea
              id="query"
              placeholder="Describe what you want to analyze..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              disabled={loading}
              rows={3}
            />
          </div>

          {error && (
            <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-md">
              {error}
            </div>
          )}

          <Button type="submit" disabled={loading} className="w-full">
            {loading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Starting Analysis...
              </>
            ) : (
              <>
                <TrendingUp className="mr-2 h-4 w-4" />
                Start Analysis
              </>
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

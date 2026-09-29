'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { API } from '@/lib/utils'
import type { ReactResultResponse } from '@/lib/utils'
import { ReactReport } from './ReactReport'
import {
  Loader2, ArrowLeft, AlertCircle, Zap, Hash, DollarSign, Wrench
} from 'lucide-react'

/* ── ReAct Result View (Markdown Report) ──────────────────────── */

export function ReactResultPage({ threadId }: { threadId: string }) {
  const router = useRouter()
  const [result, setResult] = useState<ReactResultResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchResult = async () => {
      try {
        const data = await API.getReactResult(threadId)
        setResult(data)
      } catch (e) {
        setError(e instanceof Error ? e.message : '未知错误')
      } finally {
        setLoading(false)
      }
    }
    fetchResult()
  }, [threadId])

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="h-10 w-10 animate-spin text-blue-500 mx-auto" />
          <p className="mt-4 text-slate-600">正在加载分析报告...</p>
        </div>
      </div>
    )
  }

  if (error || !result) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white p-6">
        <div className="max-w-md mx-auto">
          <Card className="border-red-200 bg-red-50">
            <CardContent className="p-6 text-center">
              <AlertCircle className="h-12 w-12 text-red-400 mx-auto mb-4" />
              <h2 className="text-lg font-semibold text-red-700 mb-2">加载失败</h2>
              <p className="text-red-600 mb-4">{error || '未找到结果'}</p>
              <Button onClick={() => router.push('/')}>开始新分析</Button>
            </CardContent>
          </Card>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white">
      <header className="bg-white border-b sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="icon" className="no-print" onClick={() => router.push('/')}>
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <div>
              <h1 className="text-xl font-bold text-slate-900">ReAct 分析报告</h1>
              <p className="text-sm text-slate-500">{threadId.slice(0, 24)}...</p>
            </div>
          </div>
          <Badge variant="success">已完成</Badge>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 py-6">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          {/* Main content: Markdown report */}
          <div className="lg:col-span-3">
            <Card>
              <CardContent className="p-6 md:p-8">
                <ReactReport answer={result.answer} report={result.report} />
              </CardContent>
            </Card>
          </div>

          {/* Sidebar: Metadata (打印/导出 PDF 时隐藏——运营信息不进报告) */}
          <div className="space-y-4 no-print">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Zap className="h-4 w-4" />
                  分析概要
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center gap-3">
                  <Hash className="h-4 w-4 text-muted-foreground" />
                  <div>
                    <p className="text-xs text-muted-foreground">迭代次数</p>
                    <p className="font-semibold">{result.iterations}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <DollarSign className="h-4 w-4 text-muted-foreground" />
                  <div>
                    <p className="text-xs text-muted-foreground">估算成本</p>
                    <p className="font-semibold">${result.cost.toFixed(4)}</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Wrench className="h-4 w-4" />
                  已调用工具
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-2">
                  {result.tools_used.map((tool, i) => (
                    <Badge key={i} variant="outline" className="font-mono text-xs">
                      {tool}
                    </Badge>
                  ))}
                  {result.tools_used.length === 0 && (
                    <p className="text-sm text-muted-foreground">无工具调用</p>
                  )}
                </div>
              </CardContent>
            </Card>

            <div className="space-y-2">
              <Button
                className="w-full"
                variant="outline"
                onClick={() => router.push(`/monitoring?thread_id=${threadId}&mode=react`)}
              >
                查看执行详情
              </Button>
              <Button className="w-full" onClick={() => router.push('/')}>
                开始新分析
              </Button>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}

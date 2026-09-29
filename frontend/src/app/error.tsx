'use client'

// Root route error boundary (iteration 143). Next.js routes any render or
// runtime error inside the page trees below this segment here; before this
// file existed every route segment shipped only a page.tsx, so a crash fell
// through to the framework's default English crash screen. The boundary
// renders a Chinese graceful-fallback card: what happened, something
// reportable (the Next digest when present, the error message otherwise),
// a retry that re-renders the failed segment, and a way back home.
import { useEffect } from 'react'
import Link from 'next/link'
import { AlertTriangle, Home, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    // Error boundaries swallow the exception — this effect is the only place
    // the crash reaches the browser console (the Next.js error-boundary
    // logging contract).
    console.error('[app] 页面渲染异常:', error)
  }, [error])

  const identity = error.digest ?? error.message

  return (
    <div className="container mx-auto px-4 py-16 flex justify-center">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-red-600">
            <AlertTriangle className="h-5 w-5" />
            页面出错了
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            渲染此页面时发生异常。您可以重试,或返回首页继续其他操作。
          </p>
          <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
            <p className="text-xs text-muted-foreground">错误标识</p>
            <p className="break-all font-mono text-xs">{identity}</p>
          </div>
          <div className="flex gap-2">
            <Button onClick={reset}>
              <RotateCcw className="mr-1 h-4 w-4" />
              重试
            </Button>
            <Button variant="outline" asChild>
              <Link href="/">
                <Home className="mr-1 h-4 w-4" />
                返回首页
              </Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

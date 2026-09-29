'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  History, Search, FileText, ChevronLeft, ChevronRight, Loader2,
} from 'lucide-react'
import { API, type HistoryListItem, type HistoryStatsResponse } from '@/lib/utils'
import { statusZh } from '@/lib/status'

const PAGE_SIZE = 20

// 与状态徽章色系一致:completed 绿 / failed 红 / running 蓝 / 其余灰
const STATUS_BADGE_CLS: Record<string, string> = {
  completed: 'bg-green-500/10 text-green-600 border-green-500/30',
  failed: 'bg-red-500/10 text-red-600 border-red-500/30',
  running: 'bg-blue-500/10 text-blue-600 border-blue-500/30',
  degraded: 'bg-amber-500/10 text-amber-600 border-amber-500/30',
}

const badgeCls = (status: string) => STATUS_BADGE_CLS[(status || '').toLowerCase()] || 'bg-slate-500/10 text-slate-600 border-slate-500/30'

const formatDuration = (seconds: number) =>
  seconds < 60
    ? `${Math.round(seconds)} 秒`
    : `${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`

const formatDate = (iso: string) => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', { hour12: false })
}

export default function HistoryPage() {
  const [items, setItems] = useState<HistoryListItem[]>([])
  const [keyword, setKeyword] = useState('')
  const [activeKeyword, setActiveKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [stats, setStats] = useState<HistoryStatsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchList = useCallback(async (p: number, kw: string) => {
    setLoading(true)
    setError(null)
    try {
      if (kw) {
        // 搜索结果不分页(后端单次返回),页码重置
        const res = await API.searchHistory(kw)
        setItems(res.items)
        setTotal(res.count)
        setHasMore(false)
        setPage(1)
      } else {
        const res = await API.getHistory(p, PAGE_SIZE)
        setItems(res.items)
        setTotal(res.total)
        setHasMore(res.has_more)
        setPage(res.page)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载历史记录失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchList(1, '')
  }, [fetchList])

  // 统计仅一次性拉取(页面级概览,不值得为此做轮询)
  useEffect(() => {
    API.getHistoryStats().then(setStats).catch(() => {})
  }, [])

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    const kw = keyword.trim()
    setActiveKeyword(kw)
    fetchList(1, kw)
  }

  const clearSearch = () => {
    setKeyword('')
    setActiveKeyword('')
    fetchList(1, '')
  }

  const gotoPage = (p: number) => fetchList(p, '')

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="text-center space-y-3 mb-8 pt-4">
        <div className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-cyan-600 to-teal-600 shadow-lg shadow-cyan-600/20">
          <History className="h-6 w-6 text-white" />
        </div>
        <h1 className="text-3xl font-bold tracking-tight">历史分析</h1>
        <p className="text-muted-foreground text-balance max-w-2xl mx-auto">
          SQLite 持久化的历次分析记录——回看完整报告、按代码或问题检索过往研究
        </p>
      </div>

      {stats && (
        <p className="text-sm text-muted-foreground text-center tabular-nums">
          共 {stats.total_analyses} 条记录 · 已完成 {stats.completed} · 失败 {stats.failed}
        </p>
      )}

      <form onSubmit={handleSearch} className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索股票代码或研究问题..."
            className="pl-9"
            aria-label="搜索历史"
          />
        </div>
        <Button type="submit" variant="outline" disabled={loading || !keyword.trim()}>
          搜索
        </Button>
        {activeKeyword && (
          <Button type="button" variant="ghost" onClick={clearSearch}>
            清除
          </Button>
        )}
      </form>

      {error && (
        <Card className="border-red-500">
          <CardContent className="p-4 text-red-500">错误：{error}</CardContent>
        </Card>
      )}

      {loading ? (
        <div className="flex items-center justify-center gap-2 py-16 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          加载中...
        </div>
      ) : items.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center space-y-3">
            <p className="text-muted-foreground">
              {activeKeyword ? `没有匹配「${activeKeyword}」的记录` : '暂无分析记录'}
            </p>
            <Button variant="outline" asChild>
              <Link href="/">开始新分析</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {items.map((item) => (
            <Card key={item.thread_id} className="hover:shadow-md transition-shadow">
              <CardContent className="p-4 flex items-center gap-4">
                <div className="flex-1 min-w-0 space-y-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    {item.symbols.map((s) => (
                      <Badge key={s} variant="outline" className="font-mono text-xs">
                        {s}
                      </Badge>
                    ))}
                    <Badge variant="outline" className={`text-xs border ${badgeCls(item.status)}`}>
                      {statusZh(item.status)}
                    </Badge>
                  </div>
                  <p className="text-sm text-foreground truncate">{item.query || '(无研究问题)'}</p>
                  <p className="text-xs text-muted-foreground tabular-nums">
                    {formatDate(item.created_at)} · 耗时 {formatDuration(item.execution_time)}
                  </p>
                </div>
                {item.status === 'completed' ? (
                  <Button asChild size="sm" className="shrink-0">
                    <Link href={`/result?thread_id=${item.thread_id}`}>
                      <FileText className="mr-1.5 h-4 w-4" />
                      查看报告
                    </Link>
                  </Button>
                ) : (
                  <span className="text-xs text-muted-foreground shrink-0">—</span>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {!activeKeyword && !loading && items.length > 0 && (
        <div className="flex items-center justify-center gap-4 text-sm text-muted-foreground">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1 || loading}
            onClick={() => gotoPage(page - 1)}
          >
            <ChevronLeft className="h-4 w-4" />
            上一页
          </Button>
          <span className="tabular-nums">第 {page} 页 · 共 {total} 条</span>
          <Button
            variant="outline"
            size="sm"
            disabled={!hasMore || loading}
            onClick={() => gotoPage(page + 1)}
          >
            下一页
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}
    </div>
  )
}

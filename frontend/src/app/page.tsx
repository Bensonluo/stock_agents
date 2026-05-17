'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Loader2, TrendingUp, History, Search, Trash2, Clock,
  CheckCircle2, XCircle, AlertCircle, ChevronRight, Bot
} from 'lucide-react'
import { API } from '@/lib/utils'

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000') + '/api'

interface HistoryItem {
  id: number
  thread_id: string
  symbols: string[]
  query: string
  status: string
  created_at: string
  updated_at: string
  execution_time: number
}

interface HistoryResponse {
  items: HistoryItem[]
  total: number
  page: number
  page_size: number
  has_more: boolean
}

export default function HomePage() {
  const router = useRouter()
  const [tab, setTab] = useState('analyze')

  const [symbols, setSymbols] = useState('AAPL')
  const [query, setQuery] = useState('分析这只股票的投资价值')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [history, setHistory] = useState<HistoryItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [searchKeyword, setSearchKeyword] = useState('')

  const fetchHistory = async (pageNum: number = 1, keyword: string = '') => {
    setHistoryLoading(true)
    try {
      let url = `${API_BASE}/history?page=${pageNum}&page_size=10`
      if (keyword) {
        url = `${API_BASE}/history/search?keyword=${encodeURIComponent(keyword)}&limit=10`
      }

      const res = await fetch(url)
      if (!res.ok) throw new Error('获取历史记录失败')

      const data: HistoryResponse = await res.json()

      if (pageNum === 1) {
        setHistory(data.items)
      } else {
        setHistory(prev => [...prev, ...data.items])
      }
      setHasMore(data.has_more)
      setPage(pageNum)
    } catch (e) {
      console.error('获取历史记录失败:', e)
    } finally {
      setHistoryLoading(false)
    }
  }

  useEffect(() => {
    if (tab === 'history') {
      fetchHistory(1, searchKeyword)
    }
  }, [tab, searchKeyword])

  const handleAnalyze = async () => {
    setLoading(true)
    setError(null)

    const symbolList = symbols.split(',').map(s => s.trim().toUpperCase()).filter(s => s)

    if (symbolList.length === 0) {
      setError('请输入至少一个股票代码')
      setLoading(false)
      return
    }

    try {
      const data = await API.reactAnalyze({ query, symbols: symbolList })
      router.push(`/monitoring?thread_id=${data.thread_id}&mode=react`)
    } catch (e) {
      setError(e instanceof Error ? e.message : '发生错误')
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (threadId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('确定要删除这条记录吗？')) return
    try {
      await fetch(`${API_BASE}/history/${threadId}`, { method: 'DELETE' })
      setHistory(prev => prev.filter(h => h.thread_id !== threadId))
    } catch (e) {
      console.error('删除失败:', e)
    }
  }

  const viewHistory = (threadId: string) => {
    const isReact = threadId.startsWith('react-')
    if (isReact) {
      router.push(`/result?thread_id=${threadId}&mode=react`)
    } else {
      router.push(`/result?thread_id=${threadId}`)
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed': return <CheckCircle2 className="h-4 w-4 text-green-500" />
      case 'failed': return <XCircle className="h-4 w-4 text-red-500" />
      case 'running': return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />
      default: return <AlertCircle className="h-4 w-4 text-gray-400" />
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'bg-green-100 text-green-700'
      case 'failed': return 'bg-red-100 text-red-700'
      case 'running': return 'bg-blue-100 text-blue-700'
      default: return 'bg-gray-100 text-gray-600'
    }
  }

  const formatTime = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white">
      <div className="max-w-4xl mx-auto p-4 md:p-8">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-slate-900">股票分析系统</h1>
          <p className="text-slate-500 mt-2">ReAct Agent 自主决策的智能股票分析平台</p>
        </div>

        <Tabs value={tab} onValueChange={setTab} className="w-full">
          <TabsList className="grid w-full grid-cols-2 mb-6">
            <TabsTrigger value="analyze" className="flex items-center gap-2">
              <Bot className="h-4 w-4" />
              新建分析
            </TabsTrigger>
            <TabsTrigger value="history" className="flex items-center gap-2">
              <History className="h-4 w-4" />
              历史记录
            </TabsTrigger>
          </TabsList>

          <TabsContent value="analyze">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Bot className="h-5 w-5 text-blue-600" />
                  ReAct Agent 分析
                </CardTitle>
                <CardDescription>
                  输入股票代码，Agent 将自主调用工具进行多维度分析
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="symbols">股票代码</Label>
                  <Input
                    id="symbols"
                    placeholder="AAPL, TSLA, 3690.HK"
                    value={symbols}
                    onChange={(e) => setSymbols(e.target.value)}
                    disabled={loading}
                  />
                  <p className="text-xs text-muted-foreground">
                    支持美股、A股、港股，用逗号分隔多个代码
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="query">分析问题</Label>
                  <Textarea
                    id="query"
                    placeholder="描述你想了解的内容..."
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    disabled={loading}
                    rows={3}
                  />
                </div>

                {error && (
                  <div className="p-3 text-sm text-red-600 bg-red-50 rounded-lg">
                    {error}
                  </div>
                )}

                <Button
                  className="w-full"
                  size="lg"
                  onClick={handleAnalyze}
                  disabled={loading}
                >
                  {loading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      启动中...
                    </>
                  ) : (
                    <>
                      <Bot className="mr-2 h-4 w-4" />
                      开始分析
                    </>
                  )}
                </Button>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="history">
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle>分析历史</CardTitle>
                    <CardDescription>查看过往的分析记录</CardDescription>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="relative">
                      <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                      <Input
                        className="pl-8 w-48"
                        placeholder="搜索..."
                        value={searchKeyword}
                        onChange={(e) => setSearchKeyword(e.target.value)}
                      />
                    </div>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                {historyLoading && history.length === 0 ? (
                  <div className="flex items-center justify-center py-12">
                    <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
                  </div>
                ) : history.length === 0 ? (
                  <div className="text-center py-12 text-muted-foreground">
                    <History className="h-12 w-12 mx-auto mb-3 opacity-50" />
                    <p>暂无历史记录</p>
                    <p className="text-sm mt-1">开始第一次分析吧</p>
                    <Button
                      variant="outline"
                      className="mt-4"
                      onClick={() => setTab('analyze')}
                    >
                      新建分析
                    </Button>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {history.map((item) => {
                      const isReact = item.thread_id.startsWith('react-')
                      return (
                        <div
                          key={item.thread_id}
                          className="flex items-center justify-between p-4 rounded-lg border hover:bg-slate-50 cursor-pointer transition-colors"
                          onClick={() => viewHistory(item.thread_id)}
                        >
                          <div className="flex items-center gap-4 flex-1 min-w-0">
                            {getStatusIcon(item.status)}
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <span className="font-medium truncate">
                                  {item.symbols.join(', ')}
                                </span>
                                <Badge variant="outline" className={getStatusColor(item.status)}>
                                  {item.status === 'completed' ? '已完成' :
                                   item.status === 'failed' ? '失败' :
                                   item.status === 'running' ? '运行中' : '待处理'}
                                </Badge>
                                {isReact && (
                                  <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200">
                                    <Bot className="h-3 w-3 mr-1" />
                                    Agent
                                  </Badge>
                                )}
                              </div>
                              <p className="text-sm text-muted-foreground truncate mt-1">
                                {item.query || '无描述'}
                              </p>
                              <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
                                <span className="flex items-center gap-1">
                                  <Clock className="h-3 w-3" />
                                  {formatTime(item.created_at)}
                                </span>
                                {item.execution_time > 0 && (
                                  <span>{item.execution_time.toFixed(1)}秒</span>
                                )}
                              </div>
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={(e) => handleDelete(item.thread_id, e)}
                              className="text-muted-foreground hover:text-red-500"
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                            <ChevronRight className="h-4 w-4 text-muted-foreground" />
                          </div>
                        </div>
                      )
                    })}

                    {hasMore && (
                      <Button
                        variant="outline"
                        className="w-full"
                        onClick={() => fetchHistory(page + 1, searchKeyword)}
                        disabled={historyLoading}
                      >
                        {historyLoading ? (
                          <Loader2 className="h-4 w-4 animate-spin mr-2" />
                        ) : null}
                        加载更多
                      </Button>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}

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
  Loader2, History, Search, Trash2, Clock,
  CheckCircle2, XCircle, AlertCircle, ChevronRight, Sparkles,
  Swords, ShieldCheck, Scale, FlaskConical,
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

const QUICK_SYMBOLS = [
  { symbol: 'AAPL', label: 'Apple' },
  { symbol: 'MSFT', label: '微软' },
  { symbol: 'NVDA', label: '英伟达' },
  { symbol: '600519', label: '贵州茅台' },
  { symbol: '00700', label: '腾讯控股' },
]

const EXAMPLE_QUERIES = [
  '分析这只股票的投资价值',
  '多方和空方最强的论据分别是什么?',
  '当前估值处于什么区间,有哪些风险?',
  '适合长期持有还是短线交易?',
]

const CAPABILITIES = [
  {
    icon: Swords,
    title: '多空质询',
    description: 'Bull 与 Bear 各自引用证据交锋,给出最强反方观点与失效条件。',
  },
  {
    icon: ShieldCheck,
    title: '证据审计',
    description: '数据陈旧、来源冲突、缺失字段在报告前被拦截,而不是悄悄变绿。',
  },
  {
    icon: Scale,
    title: '风险委员会',
    description: '批准 / 限制 / 否决 / 观察四态门控,低风险本身永远不等于买入理由。',
  },
  {
    icon: FlaskConical,
    title: '成本化回测',
    description: '下一根 K 线成交、含佣金滑点的真实回测,信号命中率带置信下界。',
  },
]

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
    if (!confirm('确定要删除这条记录吗?')) return
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
    <div className="pb-10">
      {/* ===== Hero ===== */}
      <section className="relative overflow-hidden bg-slate-950">
        <div className="absolute inset-0 bg-grid-slate" aria-hidden />
        <div className="absolute -top-32 left-1/2 -translate-x-1/2 h-96 w-[48rem] rounded-full bg-blue-600/25 blur-3xl" aria-hidden />
        <div className="absolute -bottom-40 right-0 h-80 w-80 rounded-full bg-indigo-500/15 blur-3xl" aria-hidden />

        <div className="relative max-w-4xl mx-auto px-4 pt-16 pb-24 md:pt-20 md:pb-28 text-center">
          <div className="inline-flex items-center gap-1.5 rounded-full border border-slate-700 bg-slate-900/70 px-3 py-1 text-xs text-slate-300 mb-6">
            <Sparkles className="h-3.5 w-3.5 text-blue-400" />
            V2 · 证据约束的多 Agent 研究
          </div>
          <h1 className="text-balance text-4xl md:text-5xl font-bold tracking-tight text-white leading-tight">
            让每一次投资判断
            <span className="bg-gradient-to-r from-blue-400 to-indigo-300 bg-clip-text text-transparent">都有据可查</span>
          </h1>
          <p className="text-balance mt-4 text-slate-400 max-w-2xl mx-auto leading-relaxed">
            多 Agent 分工研究,多空双方引用证据质询;审计器拦截陈旧与冲突数据,
            风险委员会把关仓位结论——报告里的每个数字都能追溯到来源与公式。
          </p>
          <div className="mt-6 flex flex-wrap justify-center gap-2">
            {['多空质询', '证据审计', '风险委员会', '估值情景', '成本化回测'].map(tag => (
              <span key={tag} className="rounded-full bg-slate-900/80 border border-slate-700/70 px-3 py-1 text-xs text-slate-300">
                {tag}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* ===== 分析卡(悬浮于 Hero 之上) ===== */}
      <div className="max-w-4xl mx-auto px-4 -mt-16 relative z-10">
        <Tabs value={tab} onValueChange={setTab} className="w-full">
          <TabsList className="grid w-full grid-cols-2 mb-4 shadow-sm">
            <TabsTrigger value="analyze" className="flex items-center gap-2">
              <Sparkles className="h-4 w-4" />
              新建分析
            </TabsTrigger>
            <TabsTrigger value="history" className="flex items-center gap-2">
              <History className="h-4 w-4" />
              历史记录
            </TabsTrigger>
          </TabsList>

          <TabsContent value="analyze">
            <Card className="shadow-xl shadow-slate-900/10 border-slate-200/80">
              <CardContent className="p-5 md:p-6 space-y-4">
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label htmlFor="symbols">股票代码</Label>
                    <span className="text-xs text-muted-foreground">美股 · A股 · 港股</span>
                  </div>
                  <Input
                    id="symbols"
                    placeholder="如 AAPL, TSLA, 600519, 00700"
                    value={symbols}
                    onChange={(e) => setSymbols(e.target.value)}
                    disabled={loading}
                    className="h-11 text-base"
                  />
                  <div className="flex flex-wrap gap-1.5 pt-0.5">
                    {QUICK_SYMBOLS.map(({ symbol, label }) => (
                      <button
                        key={symbol}
                        type="button"
                        disabled={loading}
                        onClick={() => setSymbols(prev => {
                          const parts = prev.split(',').map(s => s.trim()).filter(Boolean)
                          return parts.includes(symbol) ? parts.filter(s => s !== symbol).join(', ') : [...parts, symbol].join(', ')
                        })}
                        className={`rounded-full border px-2.5 py-1 text-xs transition-colors disabled:opacity-50 ${
                          symbols.split(',').map(s => s.trim()).includes(symbol)
                            ? 'border-blue-600 bg-blue-50 text-blue-700 font-medium'
                            : 'border-slate-200 bg-white text-slate-600 hover:border-slate-400'
                        }`}
                      >
                        {symbol} <span className="text-slate-400">{label}</span>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="query">研究问题</Label>
                  <Textarea
                    id="query"
                    placeholder="描述你想了解的内容..."
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    disabled={loading}
                    rows={3}
                    className="text-base"
                  />
                  <div className="flex flex-wrap gap-1.5 pt-0.5">
                    {EXAMPLE_QUERIES.map(eq => (
                      <button
                        key={eq}
                        type="button"
                        disabled={loading}
                        onClick={() => setQuery(eq)}
                        className={`rounded-full border px-2.5 py-1 text-xs transition-colors disabled:opacity-50 ${
                          query === eq
                            ? 'border-indigo-600 bg-indigo-50 text-indigo-700 font-medium'
                            : 'border-slate-200 bg-white text-slate-600 hover:border-slate-400'
                        }`}
                      >
                        {eq}
                      </button>
                    ))}
                  </div>
                </div>

                {error && (
                  <div className="p-3 text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg">
                    {error}
                  </div>
                )}

                <Button
                  className="w-full h-12 text-base font-semibold shadow-lg shadow-blue-600/25"
                  size="lg"
                  onClick={handleAnalyze}
                  disabled={loading}
                >
                  {loading ? (
                    <>
                      <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                      正在启动研究...
                    </>
                  ) : (
                    <>
                      <Sparkles className="mr-2 h-5 w-5" />
                      开始研究
                    </>
                  )}
                </Button>
                <p className="text-center text-xs text-muted-foreground">
                  Agent 将自主调用数据、分析、估值与风险工具,约 1-2 分钟出报告
                </p>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="history">
            <Card className="shadow-lg shadow-slate-900/5">
              <CardHeader>
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div>
                    <CardTitle>研究历史</CardTitle>
                    <CardDescription>点击记录查看完整报告</CardDescription>
                  </div>
                  <div className="relative">
                    <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                    <Input
                      className="pl-8 w-full sm:w-48"
                      placeholder="搜索..."
                      value={searchKeyword}
                      onChange={(e) => setSearchKeyword(e.target.value)}
                    />
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
                    <p className="text-sm mt-1">开始第一次研究吧</p>
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

      {/* ===== V2 能力展示 ===== */}
      <section className="max-w-4xl mx-auto px-4 mt-12">
        <div className="text-center mb-6">
          <h2 className="text-xl font-semibold tracking-tight">这份报告和你常见的有何不同</h2>
          <p className="text-sm text-muted-foreground mt-1.5">确定性引擎负责事实,LLM 只做解释——数字不再凭空而来</p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {CAPABILITIES.map(({ icon: Icon, title, description }) => (
            <div
              key={title}
              className="group rounded-xl border border-slate-200 bg-white p-5 hover:border-blue-300 hover:shadow-md hover:shadow-blue-600/5 transition-all"
            >
              <div className="h-9 w-9 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center mb-3 group-hover:bg-blue-600 group-hover:text-white transition-colors">
                <Icon className="h-5 w-5" />
              </div>
              <h3 className="font-semibold">{title}</h3>
              <p className="text-sm text-muted-foreground mt-1 leading-relaxed">{description}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}

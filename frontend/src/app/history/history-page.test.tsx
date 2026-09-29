// @vitest-environment jsdom
// Component-level lock for the history page (iteration 153): renders the
// SQLite-persisted record list, gates 查看报告 links to completed records
// only, wires the search box to the search endpoint (submit-gated — no
// debounce, deterministic), and surfaces the client fallback error when the
// list request rejects.
//
// Mock convention (established in signal-quality-card.test.tsx): @/lib/utils
// is a dual-purpose module (API client + shadcn cn()) — an integral module
// mock starves Card/Label/Button of cn before the first assertion, so we
// partially mock: spread the actual module and override only the three API
// methods this page calls (getHistory / searchHistory / getHistoryStats).
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// vi.mock factories are hoisted above every const — the shared spies must be
// created hoisted too or the factory reads them before initialization.
const getHistory = vi.hoisted(() => vi.fn())
const searchHistory = vi.hoisted(() => vi.fn())
const getHistoryStats = vi.hoisted(() => vi.fn())

vi.mock('@/lib/utils', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/utils')>()
  return {
    ...actual,
    API: {
      ...actual.API,
      getHistory,
      searchHistory,
      getHistoryStats,
    },
  }
})

import HistoryPage from './page'
import type { HistoryListItem } from '@/lib/utils'

const item = (over: Pick<HistoryListItem, 'thread_id' | 'symbols' | 'query' | 'status' | 'execution_time' | 'created_at'>): HistoryListItem => ({
  id: 1,
  updated_at: over.created_at,
  ...over,
})

const LIST_RESPONSE = {
  items: [
    item({ thread_id: 't-001', symbols: ['AAPL'], query: '苹果财报分析', status: 'completed', execution_time: 83.2, created_at: '2026-09-28T10:00:00Z' }),
    item({ thread_id: 't-002', symbols: ['600000'], query: '浦发银行基本面', status: 'failed', execution_time: 12.4, created_at: '2026-09-28T11:00:00Z' }),
  ],
  total: 2,
  page: 1,
  page_size: 20,
  has_more: false,
}

beforeEach(() => {
  getHistory.mockReset()
  searchHistory.mockReset()
  getHistoryStats.mockReset()
  getHistory.mockResolvedValue(LIST_RESPONSE)
  getHistoryStats.mockResolvedValue({
    total_analyses: 12, completed: 10, failed: 2, pending: 0, running: 0,
  })
})

describe('HistoryPage record list', () => {
  it('renders records with localized statuses and gates links to completed only', async () => {
    render(<HistoryPage />)

    expect(await screen.findByText('苹果财报分析')).toBeInTheDocument()
    expect(screen.getByText('浦发银行基本面')).toBeInTheDocument()

    // 状态走共享词表:已完成 / 失败
    expect(screen.getByText('已完成')).toBeInTheDocument()
    expect(screen.getByText('失败')).toBeInTheDocument()

    // 统计行渲染
    expect(screen.getByText(/共 12 条记录/)).toBeInTheDocument()

    // 只有 completed 记录能进结果页
    const links = screen.getAllByRole('link', { name: /查看报告/ })
    expect(links).toHaveLength(1)
    expect(links[0]).toHaveAttribute('href', '/result?thread_id=t-001')

    expect(getHistory).toHaveBeenCalledWith(1, 20)
  })

  it('searches via the search endpoint on submit and returns to the list on clear', async () => {
    searchHistory.mockResolvedValue({
      items: [item({ thread_id: 't-003', symbols: ['MSFT'], query: '微软云业务', status: 'completed', execution_time: 60, created_at: '2026-09-29T09:00:00Z' })],
      keyword: 'MSFT',
      count: 1,
    })

    render(<HistoryPage />)
    await screen.findByText('苹果财报分析')

    fireEvent.change(screen.getByLabelText('搜索历史'), { target: { value: 'MSFT' } })
    fireEvent.click(screen.getByRole('button', { name: '搜索' }))

    expect(await screen.findByText('微软云业务')).toBeInTheDocument()
    expect(searchHistory).toHaveBeenCalledWith('MSFT')
    expect(screen.queryByText('苹果财报分析')).not.toBeInTheDocument()

    // 清除搜索回到全量列表
    fireEvent.click(screen.getByRole('button', { name: '清除' }))
    expect(await screen.findByText('苹果财报分析')).toBeInTheDocument()
    expect(getHistory).toHaveBeenCalledTimes(2)
  })

  it('surfaces the fallback error when the list request rejects', async () => {
    getHistory.mockRejectedValue(new Error('backend down'))

    render(<HistoryPage />)

    expect(await screen.findByText('错误：backend down')).toBeInTheDocument()
  })
})

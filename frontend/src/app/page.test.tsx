// @vitest-environment jsdom
// Component-level lock for the home page's two submit guards (handleAnalyze)
// and the happy-path wiring around them. Until now only tsc/lint/build
// watched this page: a cleared symbols field must surface 请输入至少一个股票代码
// client-side instead of POSTing an empty list, and a blank query must
// surface 请输入研究问题 (iteration 138, commit 69d19b5) instead of shipping
// an empty research question. The happy-path test pins the reactAnalyze
// payload shape and the monitoring redirect that follows.
//
// Mock convention (established in signal-quality-card.test.tsx): @/lib/utils
// is a dual-purpose module (API client + shadcn cn()) — an integral module
// mock starves Card/Label/Button of cn before the first assertion, so we
// partially mock: spread the actual module and override only API.reactAnalyze,
// the single API method this page calls.
//
// Page-specific landmines:
// - page.tsx calls useRouter() at render; jsdom has no Next router, so
//   next/navigation is stubbed with a spy push.
// - The history tab renders SignalQualityCard, which self-fetches on mount —
//   the whole child is stubbed (we are not testing it here). The history
//   fetch itself only fires when tab === 'history' (default 'analyze'), so
//   no raw fetch stub is needed.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// vi.mock factories are hoisted above every const — the shared spies must be
// created hoisted too or the factories read them before initialization.
const reactAnalyze = vi.hoisted(() => vi.fn())
const push = vi.hoisted(() => vi.fn())

vi.mock('@/lib/utils', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/utils')>()
  return {
    ...actual,
    API: {
      ...actual.API,
      reactAnalyze,
    },
  }
})

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
}))

vi.mock('@/components/history/SignalQualityCard', () => ({
  SignalQualityCard: () => <div data-testid="signal-quality-card" />,
}))

import HomePage from './page'

beforeEach(() => {
  reactAnalyze.mockReset()
  push.mockReset()
})

describe('HomePage analyze form guards (handleAnalyze)', () => {
  it('blocks submit when every symbol is cleared — named error, no API call', async () => {
    render(<HomePage />)

    // Input defaults to 'AAPL'; clearing it empties the parsed symbol list.
    const symbols = await screen.findByLabelText(/股票代码/)
    fireEvent.change(symbols, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: /开始研究/ }))

    expect(await screen.findByText('请输入至少一个股票代码')).toBeInTheDocument()
    expect(reactAnalyze).not.toHaveBeenCalled()
  })

  it('blocks submit when the query is cleared — named error, no API call (iteration 138)', async () => {
    render(<HomePage />)

    // Symbols keep their default; only the query textarea is emptied.
    const query = await screen.findByLabelText(/研究问题/)
    fireEvent.change(query, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: /开始研究/ }))

    expect(await screen.findByText('请输入研究问题')).toBeInTheDocument()
    expect(reactAnalyze).not.toHaveBeenCalled()
  })

  it('blocks submit above the symbol-count cap — named error, no API call (iteration 174)', async () => {
    render(<HomePage />)

    // 11 comma-separated valid tickers cross the 10-symbol cap; the client
    // guard mirrors MAX_SYMBOLS_PER_REQUEST (backend is authoritative — a
    // drifted local guard still gets 422'd by the server validator).
    const symbols = await screen.findByLabelText(/股票代码/)
    fireEvent.change(symbols, {
      target: { value: 'A,B,C,D,E,F,G,H,I,J,K' },
    })
    fireEvent.click(screen.getByRole('button', { name: /开始研究/ }))

    expect(await screen.findByText('最多支持 10 个股票代码')).toBeInTheDocument()
    expect(reactAnalyze).not.toHaveBeenCalled()
  })

  it('wires the happy path: reactAnalyze payload then monitoring redirect', async () => {
    reactAnalyze.mockResolvedValue({ thread_id: 'react-test-1' })
    render(<HomePage />)

    // Defaults untouched: symbols 'AAPL', query '分析这只股票的投资价值'.
    await screen.findByLabelText(/股票代码/)
    fireEvent.click(screen.getByRole('button', { name: /开始研究/ }))

    await waitFor(() => expect(reactAnalyze).toHaveBeenCalledTimes(1))
    expect(reactAnalyze).toHaveBeenCalledWith({
      query: '分析这只股票的投资价值',
      symbols: ['AAPL'],
    })
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith('/monitoring?thread_id=react-test-1&mode=react')
    )
  })
})

describe('HomePage history tab entry to the full history page', () => {
  it('links to /history from the history tab (iteration 172)', async () => {
    // 历史列表是裸 fetch(不走 API client);tab 默认 analyze 不触发,切 tab 才拉
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0, page: 1, page_size: 10, has_more: false }),
    }))

    render(<HomePage />)

    // Radix Tabs 在 jsdom 里 click/pointerDown 都不触发激活(aria-selected
    // 不变),键盘 Enter 路径稳定——实证钉死,勿改回 click。
    fireEvent.keyDown(screen.getByRole('tab', { name: /历史记录/ }), { key: 'Enter' })

    const link = await screen.findByRole('link', { name: /完整历史/ })
    expect(link).toHaveAttribute('href', '/history')
    vi.unstubAllGlobals()
  })
})

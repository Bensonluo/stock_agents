// @vitest-environment jsdom
// The first component-level test (round 4 of the frontend regression net).
// SignalQualityCard is the most judgment-dense surface in the app — it wires
// the verdict text, the Newey-West preference, the dedup disclosure and the
// honest thin-history branch together, and until now only tsc/lint/build
// watched that wiring. Only the five fetch methods are mocked, via a
// partial mock (importOriginal): '@/lib/utils' is dual-purpose — the API
// client AND the shadcn `cn()` helper every UI primitive imports — so
// replacing the whole module starves Card/Select/Button of `cn` and the
// render dies before the first assertion. Companion views are stubbed to
// reject so their quiet-failure wiring is asserted alongside the main branch.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { SignalQualityCard } from '@/components/history/SignalQualityCard'
import {
  API,
  type DecisionICResponse,
  type ICDecayResponse,
  type TopKPortfolioResponse,
} from '@/lib/utils'

vi.mock('@/lib/utils', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/utils')>()
  return {
    ...actual,
    API: {
      getDecisionIC: vi.fn(),
      getDecisionICDecay: vi.fn(),
      getConfidenceCalibration: vi.fn(),
      getRegimeConditionalIC: vi.fn(),
      getTopKPortfolio: vi.fn(),
    },
  }
})

const okFixture: DecisionICResponse = {
  method: 'spearman_rank_ic',
  horizon_bars: 20,
  records_examined: 10,
  runs_evaluated: 5,
  runs_pending_maturity: 3,
  runs_skipped: 2,
  runs_duplicate: 1,
  per_run: [
    { thread_id: 't1', date: '2026-09-20', symbols: 6, ic: 0.25 },
    { thread_id: 't2', date: '2026-09-21', symbols: 6, ic: -0.1 },
  ],
  dimensions: {
    technical: {
      runs: 5,
      ic_mean: 0.18,
      ic_std: 0.1,
      icir: 1.8,
      t_stat: 2.4,
      t_stat_nw: 1.2,
      ic_positive_rate: 0.6,
    },
  },
  caveat: '历史 run 由演化中的决策公式产生，IC 跨版本聚合',
  status: 'ok',
  ic_mean: 0.123,
  ic_std: 0.08,
  icir: 1.53,
  // Raw t would read "signal" (2.6 ≥ 2), but overlapping forward windows
  // inflate it — the Newey-West t is the honest verdict basis (iteration 123).
  t_stat: 2.6,
  t_stat_nw: 1.4,
  ic_positive_rate: 0.6,
}

const thinFixture: DecisionICResponse = {
  method: 'spearman_rank_ic',
  horizon_bars: 20,
  records_examined: 3,
  runs_evaluated: 0,
  runs_pending_maturity: 2,
  runs_skipped: 1,
  runs_duplicate: 0,
  per_run: [],
  caveat: '历史 run 由演化中的决策公式产生，IC 跨版本聚合',
  status: 'insufficient_history',
}

beforeEach(() => {
  vi.mocked(API.getDecisionIC).mockReset()
  // Companions fail quietly — their sections must render nothing, which the
  // ok-branch test asserts negatively.
  vi.mocked(API.getDecisionICDecay)
    .mockReset()
    .mockRejectedValue(new Error('offline'))
  vi.mocked(API.getConfidenceCalibration)
    .mockReset()
    .mockRejectedValue(new Error('offline'))
  vi.mocked(API.getRegimeConditionalIC)
    .mockReset()
    .mockRejectedValue(new Error('offline'))
  vi.mocked(API.getTopKPortfolio)
    .mockReset()
    .mockRejectedValue(new Error('offline'))
})

describe('SignalQualityCard', () => {
  it('renders the NW-based verdict, stat tiles, dedup disclosure and per-run rows after fetch', async () => {
    vi.mocked(API.getDecisionIC).mockResolvedValue(okFixture)
    render(<SignalQualityCard />)

    // Raw t = 2.6 would say "significant"; NW = 1.4 keeps the verdict honest.
    expect(
      await screen.findByText('尚无法与随机排序区分——需要更多已成熟的多标的 run')
    ).toBeInTheDocument()

    // Stat tiles carry the aggregate values; the t tile shows NW with its
    // provenance mark.
    expect(screen.getByText('IC 均值')).toBeInTheDocument()
    expect(screen.getByText('0.123')).toBeInTheDocument()
    expect(screen.getByText('t 统计量 · NW')).toBeInTheDocument()
    expect(screen.getByText('1.40')).toBeInTheDocument()

    // Counts line discloses deduped duplicates (iteration 130).
    expect(screen.getByText(/5 个 run 已评估/)).toBeInTheDocument()
    expect(screen.getByText(/1 条重复已剔除/)).toBeInTheDocument()

    // Per-run rows render signed ICs.
    expect(screen.getByText('+0.250')).toBeInTheDocument()
    expect(screen.getByText('-0.100')).toBeInTheDocument()

    // Companion views failed quietly — no calib / regime / topk sections.
    expect(screen.queryByText('Brier 分')).not.toBeInTheDocument()
    expect(screen.queryByText(/市场状态分桶/)).not.toBeInTheDocument()
    expect(screen.queryByText(/照做收益/)).not.toBeInTheDocument()
  })

  it('renders the honest insufficient-history branch and never fabricates a verdict', async () => {
    vi.mocked(API.getDecisionIC).mockResolvedValue(thinFixture)
    render(<SignalQualityCard />)

    expect(await screen.findByText('历史尚不足以计算截面 IC')).toBeInTheDocument()
    expect(screen.getByText(/3 条记录/)).toBeInTheDocument()
    expect(screen.queryByText(/显著预测了前向收益/)).not.toBeInTheDocument()
  })

  it('shows the honest error message when the IC endpoint rejects', async () => {
    vi.mocked(API.getDecisionIC).mockRejectedValue(new Error('backend down'))
    render(<SignalQualityCard />)

    expect(await screen.findByText('信号质量评估暂不可用')).toBeInTheDocument()
  })
})

describe('SignalQualityCard interactions', () => {
  // Interaction tests stick to the card's plain Buttons (decay chips, top-k
  // selector): fireEvent.click covers them without user-event or Radix
  // Select portal plumbing. These pin the wiring three iterations built —
  // chips switch the main window (75), the 5d point must be reachable
  // (130), and the money view refetches per k (122).

  it('switches the horizon window when the 5d decay chip is clicked and refetches', async () => {
    vi.mocked(API.getDecisionIC)
      .mockResolvedValueOnce(okFixture)
      .mockResolvedValueOnce({ ...okFixture, horizon_bars: 5, ic_mean: 0.321 })
    vi.mocked(API.getDecisionICDecay).mockResolvedValue({
      method: 'spearman_rank_ic',
      status: 'ok',
      caveat: '历史 run 由演化中的决策公式产生，IC 跨版本聚合',
      horizons: [
        {
          method: 'spearman_rank_ic',
          horizon_bars: 5,
          records_examined: 10,
          runs_evaluated: 5,
          runs_pending_maturity: 3,
          runs_skipped: 2,
          runs_duplicate: 1,
          per_run: [],
          caveat: '历史 run 由演化中的决策公式产生，IC 跨版本聚合',
          status: 'ok',
          ic_mean: 0.1,
        },
      ],
    })
    render(<SignalQualityCard />)

    // Initial load fetches the default 20-day window.
    await screen.findByText('0.123')
    expect(vi.mocked(API.getDecisionIC)).toHaveBeenLastCalledWith(20)

    // Click the shortest decay point — iteration 130 made it a first-class
    // horizon so the trigger never goes blank.
    fireEvent.click(screen.getByText('5d'))
    await waitFor(() =>
      expect(vi.mocked(API.getDecisionIC)).toHaveBeenLastCalledWith(5)
    )
    // The refreshed aggregate for the new window renders (distinct IC mean).
    await screen.findByText('0.321')
    // The clicked chip carries the active styling.
    expect(screen.getByText('5d')).toHaveClass('bg-primary')
  })

  it('refetches the money view when a top-k selector button is clicked', async () => {
    const topkBase: TopKPortfolioResponse = {
      method: 'equal_weight_replay',
      top_k: 1,
      horizon_bars: 20,
      records_examined: 10,
      runs_evaluated: 5,
      runs_pending_maturity: 3,
      runs_skipped: 2,
      runs_duplicate: 1,
      runs_narrow: 0,
      caveat: '回放口径为毛收益（不含成本与滑点）；基准为全截面等权',
      status: 'ok',
      excess_mean: 0.034,
      per_run: [
        {
          thread_id: 't1',
          date: '2026-09-20',
          symbols: 6,
          top_return: 0.05,
          baseline_return: 0.016,
          excess: 0.034,
        },
      ],
    }
    vi.mocked(API.getDecisionIC).mockResolvedValue(okFixture)
    vi.mocked(API.getTopKPortfolio)
      .mockResolvedValueOnce(topkBase)
      .mockResolvedValueOnce({ ...topkBase, top_k: 3, excess_mean: -0.012 })
    render(<SignalQualityCard />)

    // The money view lands with the default k=1.
    await screen.findByText(/照做收益 · 前 1 名等权/)
    expect(vi.mocked(API.getTopKPortfolio)).toHaveBeenLastCalledWith(20, 1)

    fireEvent.click(screen.getByText('前3'))
    await waitFor(() =>
      expect(vi.mocked(API.getTopKPortfolio)).toHaveBeenLastCalledWith(20, 3)
    )
    // The refreshed view renders the new k and its (negative) excess.
    await screen.findByText(/照做收益 · 前 3 名等权/)
    expect(screen.getByText(/平均超额 -1\.20%/)).toBeInTheDocument()
    expect(screen.getByText('前3')).toHaveClass('bg-primary')
  })
})

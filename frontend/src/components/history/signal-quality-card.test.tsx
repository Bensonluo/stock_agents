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
import { render, screen } from '@testing-library/react'
import { SignalQualityCard } from '@/components/history/SignalQualityCard'
import { API, type DecisionICResponse } from '@/lib/utils'

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

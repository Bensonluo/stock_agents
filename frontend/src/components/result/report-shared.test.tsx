// @vitest-environment jsdom
// Component-level pins for OptionImpliedBlock — the options annotation UI
// shared by ReactReport (ReAct view) and RiskAssessment (pipeline view).
// The pure helpers (optionImpliedBadge / hasOptionImpliedContent) are
// already pinned in report-shared.test.ts; this file locks what actually
// lands in the DOM: every metric row of a full smoke-run payload, the
// amber term-inversion warning, the three regime badge tones, and the
// honest-absence branches. Wire shapes mirror
// app/tools/data/option_signals.py::build_option_implied:
// insufficient_data means regime is null, but qvix/iv/pcr sub-dicts may
// still carry partial values — and an all-null block renders NOTHING at
// all (hasOptionImpliedContent gates the whole component), so a
// 数据不足 badge can only ever appear alongside at least one value row.
// No '@/lib/utils' mock needed: OptionImpliedBlock reads no API methods,
// and the real cn() import has no side effects.
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { OptionImpliedBlock, ConsensusBlock } from './report-shared'
import type {
  Consensus, ConsensusEpsForecast, ConsensusRatings, ConsensusTargetPrice,
  OptionImplied, OptionImpliedIv,
} from './types'

const ivFixture = (overrides: Partial<OptionImpliedIv> = {}): OptionImpliedIv => ({
  status: 'ok',
  atm_iv_near: 0.202,
  near_expiry: '2026-10-16',
  atm_iv_next: 0.254,
  next_expiry: '2026-11-20',
  term_structure: 0.008,
  skew_25d: 0.021,
  n_contracts: 580,
  n_filtered: 549,
  ...overrides,
})

const block = (overrides: Partial<OptionImplied> = {}): OptionImplied => ({
  status: 'ok',
  regime: '自满',
  qvix: {
    // Production smoke run: QVIX 14.85 at the 13.9% 1-year rank → 自满.
    current: 14.85,
    as_of: '2026-09-29',
    percentile_1y: 0.139,
    history_days: 250,
  },
  iv: ivFixture(),
  pcr: { market_pcr: 0.92, by_underlying: { '510300': 0.88 } },
  generated_at: '2026-09-29T15:00:00',
  ...overrides,
})

describe('OptionImpliedBlock', () => {
  it('renders every field of a full ok payload (smoke-run values, 自满 badge)', () => {
    render(<OptionImpliedBlock block={block()} />)

    // Header + regime badge. 0.139 percentile → 自满 per backend thresholds
    // (<= 0.20); the sky tone is the calm-regime style.
    expect(screen.getByText('期权隐含情绪（CN 场内期权）')).toBeInTheDocument()
    const badge = screen.getByText('自满')
    expect(badge).toHaveClass('bg-sky-100', 'text-sky-700')

    // QVIX row: point level, 1-year rank (0 decimals), as-of date.
    expect(screen.getByText('QVIX（中国波指）')).toBeInTheDocument()
    expect(screen.getByText('14.85')).toBeInTheDocument()
    expect(screen.getByText('· 1年分位 14%')).toBeInTheDocument()
    expect(screen.getByText('截至 2026-09-29')).toBeInTheDocument()

    // ATM IV row: near-month as the primary value, next-month inline.
    expect(screen.getByText('ATM 隐含波动率')).toBeInTheDocument()
    expect(screen.getByText('20.2%（近月）')).toBeInTheDocument()
    expect(screen.getByText('次月 25.4%')).toBeInTheDocument()

    // Term structure (positive here) and skew rows.
    expect(screen.getByText('期限结构（近月−次月）')).toBeInTheDocument()
    expect(screen.getByText('+0.8%')).toBeInTheDocument()
    expect(screen.getByText('25Δ 偏度（正 = 下行保护贵）')).toBeInTheDocument()
    expect(screen.getByText('+2.1%')).toBeInTheDocument()

    // Market PCR row and the annotation-only footer with the filtered
    // contract count (n_filtered — n_contracts is never displayed).
    expect(screen.getByText('市场 PCR（认沽/认购）')).toBeInTheDocument()
    expect(screen.getByText('0.92')).toBeInTheDocument()
    expect(screen.getByText('549 份筛选后合约 · 纯标注，不影响评分')).toBeInTheDocument()
  })

  it('renders the amber inversion warning when term_structure is negative', () => {
    render(<OptionImpliedBlock block={block({ iv: ivFixture({ term_structure: -0.015 }) })} />)

    expect(screen.getByText('⚠ 近月高于次月——期限倒挂（近端恐慌）')).toBeInTheDocument()
    // The inverted value itself turns amber.
    expect(screen.getByText('-1.5%')).toHaveClass('text-amber-600')
  })

  it('renders no inversion warning for positive or zero term structures', () => {
    const { rerender } = render(<OptionImpliedBlock block={block()} />)
    expect(screen.queryByText(/期限倒挂/)).not.toBeInTheDocument()
    expect(screen.getByText('+0.8%')).toHaveClass('text-slate-600')

    // Zero is not inverted (strict < 0) and formats with the + sign.
    rerender(<OptionImpliedBlock block={block({ iv: ivFixture({ term_structure: 0 }) })} />)
    expect(screen.queryByText(/期限倒挂/)).not.toBeInTheDocument()
    expect(screen.getByText('+0.0%')).toHaveClass('text-slate-600')
  })

  it('styles the 恐慌 badge red and the 中性 badge slate', () => {
    const { unmount } = render(
      // Percentiles mirror the backend thresholds: >= 0.80 恐慌, else 中性.
      <OptionImpliedBlock block={block({ regime: '恐慌', qvix: { current: 38.21, as_of: '2026-09-29', percentile_1y: 0.93, history_days: 250 } })} />
    )
    expect(screen.getByText('恐慌')).toHaveClass('bg-red-100', 'text-red-700')
    unmount()

    render(
      <OptionImpliedBlock block={block({ regime: '中性', qvix: { current: 21.4, as_of: '2026-09-29', percentile_1y: 0.55, history_days: 250 } })} />
    )
    expect(screen.getByText('中性')).toHaveClass('bg-slate-100', 'text-slate-600')
  })

  it('renders nothing at all for an all-null insufficient_data block', () => {
    const emptyIv = ivFixture({
      status: 'insufficient_data',
      atm_iv_near: null,
      atm_iv_next: null,
      term_structure: null,
      skew_25d: null,
      n_contracts: 0,
      n_filtered: 0,
    })
    const { container } = render(
      <OptionImpliedBlock block={block({ status: 'insufficient_data', regime: null, qvix: null, iv: emptyIv, pcr: { market_pcr: null, by_underlying: {} } })} />
    )
    // hasOptionImpliedContent gates the whole component: no badge, no rows.
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the amber 数据不足 badge with partial rows for insufficient_data — and omits absent rows', () => {
    // Degraded run: no QVIX percentile → no regime, but the QVIX point
    // level and IV metrics still land on the wire.
    render(
      <OptionImpliedBlock
        block={block({
          status: 'insufficient_data',
          regime: null,
          qvix: { current: 14.85, as_of: '2026-09-29', percentile_1y: null, history_days: 250 },
          iv: null,
          pcr: null,
        })}
      />
    )

    expect(screen.getByText('数据不足')).toHaveClass('bg-amber-100', 'text-amber-700')
    // The one metric that exists still renders…
    expect(screen.getByText('14.85')).toBeInTheDocument()
    // …but no percentile (absent on the wire) and no IV/PCR rows at all.
    expect(screen.queryByText(/1年分位/)).not.toBeInTheDocument()
    expect(screen.queryByText('ATM 隐含波动率')).not.toBeInTheDocument()
    expect(screen.queryByText('市场 PCR（认沽/认购）')).not.toBeInTheDocument()
    expect(screen.queryByText('25Δ 偏度（正 = 下行保护贵）')).not.toBeInTheDocument()
  })

  it('treats ok status with a null regime as 数据不足 — never fabricates 中性', () => {
    // Defensive shape (backend pairs ok with a non-null regime); the badge
    // must stay honest rather than invent the middle label.
    render(
      <OptionImpliedBlock
        block={block({ status: 'ok', regime: null, iv: null, pcr: null })}
      />
    )
    expect(screen.getByText('数据不足')).toBeInTheDocument()
    expect(screen.queryByText('中性')).not.toBeInTheDocument()
  })

  it('renders a degraded shape without crashing: QVIX value only, empty IV metrics, no footer count', () => {
    render(
      <OptionImpliedBlock
        block={block({
          status: 'insufficient_data',
          regime: null,
          qvix: { current: 14.85, as_of: null, percentile_1y: null, history_days: 0 },
          iv: ivFixture({
            status: 'insufficient_data',
            atm_iv_near: null,
            atm_iv_next: null,
            term_structure: null,
            skew_25d: null,
            n_contracts: 580,
            n_filtered: 0,
          }),
          pcr: null,
        })}
      />
    )

    // QVIX point level renders bare: no percentile, no as-of date.
    expect(screen.getByText('14.85')).toBeInTheDocument()
    expect(screen.queryByText(/1年分位/)).not.toBeInTheDocument()
    expect(screen.queryByText(/截至/)).not.toBeInTheDocument()
    // IV fully filtered out → no IV rows; n_filtered = 0 drops the footer's
    // contract-count prefix, and n_contracts never renders anywhere.
    expect(screen.queryByText('ATM 隐含波动率')).not.toBeInTheDocument()
    expect(screen.queryByText(/份筛选后合约/)).not.toBeInTheDocument()
    expect(screen.queryByText(/580/)).not.toBeInTheDocument()
    expect(screen.getByText('纯标注，不影响评分')).toBeInTheDocument()
  })
})

/* ── ConsensusBlock ──────────────────────────────────────────────
 * DOM pins for the CN analyst-consensus annotation (iteration 163's
 * wire contract, mirrored in ./types.ts): full ok payload, the amber
 * ratings-only degraded state, per-sub-block absence, negative color
 * routing, and the honest-absence gate. Value rows assert each span
 * separately: RTL's default text matcher only sees an element's DIRECT
 * text nodes (nested spans are invisible to it), so a row's suffixes
 * (· N 家机构, 同比 ±x%, · 主导 …) are pinned as their own spans. */

const epsFixture = (overrides: Partial<ConsensusEpsForecast> = {}): ConsensusEpsForecast => ({
  year1: 2026,
  eps_mean: 2.15,
  org_count: 5,
  industry_avg: 2.31,
  year2: 2027,
  eps_mean_year2: 2.28,
  implied_growth: 0.062,
  ...overrides,
})

const tpFixture = (overrides: Partial<ConsensusTargetPrice> = {}): ConsensusTargetPrice => ({
  count: 12,
  mean: 12.5,
  median: 12.0,
  window_days: 180,
  implied_upside: 0.032,
  ...overrides,
})

const ratingsFixture = (overrides: Partial<ConsensusRatings> = {}): ConsensusRatings => ({
  counts: { '买入': 12, '增持': 8, '中性': 0, '减持': 0, '卖出': 0 },
  dominant: '买入',
  total: 20,
  ...overrides,
})

const consensus = (overrides: Partial<Consensus> = {}): Consensus => ({
  status: 'ok',
  eps_forecast: epsFixture(),
  target_price: tpFixture(),
  ratings: ratingsFixture(),
  ...overrides,
})

describe('ConsensusBlock', () => {
  it('renders every field of a full ok payload (机构预期 badge)', () => {
    render(<ConsensusBlock symbol="600000" consensus={consensus()} />)

    expect(screen.getByText('分析师一致预期（CN）')).toBeInTheDocument()
    expect(screen.getByText('机构预期')).toHaveClass('bg-slate-100', 'text-slate-600')

    // EPS year1: mean + org count + industry average (each span's own text).
    expect(screen.getByText('EPS 预测（2026 年）')).toBeInTheDocument()
    expect(screen.getByText('¥2.15')).toBeInTheDocument()
    expect(screen.getByText('· 5 家机构')).toBeInTheDocument()
    expect(screen.getByText('· 行业 ¥2.31')).toBeInTheDocument()

    // EPS year2: mean + colored implied growth.
    expect(screen.getByText('EPS 预测（2027 年）')).toBeInTheDocument()
    expect(screen.getByText('¥2.28')).toBeInTheDocument()
    expect(screen.getByText('同比 +6.2%')).toHaveClass('text-green-600')

    // Target price: mean + median + colored implied upside.
    expect(screen.getByText('目标价（12 家 · 近180天）')).toBeInTheDocument()
    expect(screen.getByText('¥12.50')).toBeInTheDocument()
    expect(screen.getByText('· 中位 ¥12.00')).toBeInTheDocument()
    expect(screen.getByText('· +3.2%')).toHaveClass('text-green-600')

    // Ratings: nonzero labels only + dominant.
    expect(screen.getByText('机构评级')).toBeInTheDocument()
    expect(screen.getByText('买入 12 · 增持 8')).toBeInTheDocument()
    expect(screen.getByText('· 主导 买入')).toBeInTheDocument()

    expect(screen.getByText('20 条评级 · 纯标注，不影响评分')).toBeInTheDocument()
  })

  it('shows the amber 数据不足 badge for ratings-only runs but still renders the ratings', () => {
    render(
      <ConsensusBlock
        symbol="600000"
        consensus={consensus({ status: 'insufficient_data', eps_forecast: undefined, target_price: undefined })}
      />
    )

    expect(screen.getByText('数据不足')).toHaveClass('bg-amber-100', 'text-amber-700')
    expect(screen.getByText('买入 12 · 增持 8')).toBeInTheDocument()
    expect(screen.getByText('· 主导 买入')).toBeInTheDocument()
    expect(screen.getByText('20 条评级 · 纯标注，不影响评分')).toBeInTheDocument()
    expect(screen.queryByText(/EPS 预测/)).not.toBeInTheDocument()
    expect(screen.queryByText(/目标价/)).not.toBeInTheDocument()
  })

  it('renders eps-only payloads without target-price or ratings rows', () => {
    render(
      <ConsensusBlock
        symbol="600000"
        consensus={consensus({ target_price: undefined, ratings: undefined })}
      />
    )

    expect(screen.getByText('EPS 预测（2026 年）')).toBeInTheDocument()
    expect(screen.queryByText(/目标价/)).not.toBeInTheDocument()
    expect(screen.queryByText(/机构评级/)).not.toBeInTheDocument()
    // No ratings → the footer's rating-count prefix drops.
    expect(screen.getByText('纯标注，不影响评分')).toBeInTheDocument()
  })

  it('colors negative implied growth and upside red', () => {
    render(
      <ConsensusBlock
        symbol="600000"
        consensus={consensus({
          eps_forecast: epsFixture({ implied_growth: -0.045 }),
          target_price: tpFixture({ implied_upside: -0.056 }),
        })}
      />
    )

    expect(screen.getByText('· -5.6%')).toHaveClass('text-red-600')
    expect(screen.getByText('同比 -4.5%')).toHaveClass('text-red-600')
  })

  it('renders a degraded eps block bare: no org count, industry avg, or year2', () => {
    render(
      <ConsensusBlock
        symbol="600000"
        consensus={consensus({
          eps_forecast: epsFixture({
            org_count: null,
            industry_avg: null,
            year2: undefined,
            eps_mean_year2: undefined,
            implied_growth: undefined,
          }),
          target_price: undefined,
          ratings: undefined,
        })}
      />
    )

    expect(screen.getByText('¥2.15')).toBeInTheDocument()
    expect(screen.queryByText(/家机构/)).not.toBeInTheDocument()
    expect(screen.queryByText(/行业/)).not.toBeInTheDocument()
    expect(screen.queryByText('EPS 预测（2027 年）')).not.toBeInTheDocument()
    expect(screen.getByText('纯标注，不影响评分')).toBeInTheDocument()
  })

  it('renders nothing at all when every sub-block is absent', () => {
    const { container } = render(
      <ConsensusBlock
        symbol="600000"
        consensus={consensus({
          status: 'insufficient_data',
          eps_forecast: undefined,
          target_price: undefined,
          ratings: undefined,
        })}
      />
    )
    // hasConsensusContent gates the whole component: no badge, no rows.
    expect(container).toBeEmptyDOMElement()
  })

  it('routes the currency by symbol: HK symbols format as HK$', () => {
    render(
      <ConsensusBlock
        symbol="0700.HK"
        consensus={consensus({ target_price: undefined, ratings: undefined })}
      />
    )

    expect(screen.getByText('HK$2.15')).toBeInTheDocument()
    expect(screen.getByText('· 行业 HK$2.31')).toBeInTheDocument()
  })
})

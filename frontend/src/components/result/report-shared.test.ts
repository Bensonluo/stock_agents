// Regression pins for the option-implied annotation block's pure helpers.
// The badge mapping and the render gate encode the wire contract of
// app/tools/data/option_signals.py::build_option_implied: an absent QVIX
// percentile must surface as an honest amber「数据不足」— never a fabricated
// 「中性」— and an all-null block must render nothing at all. The tests pin
// CURRENT behavior; changing a mapping is a visible decision.
import { describe, it, expect } from 'vitest'
import { optionImpliedBadge, hasOptionImpliedContent } from './report-shared'
import type { OptionImplied } from './types'

const block = (overrides: Partial<OptionImplied> = {}): OptionImplied => ({
  status: 'ok',
  regime: '中性',
  qvix: null,
  iv: null,
  pcr: null,
  generated_at: '2026-09-30T00:00:00',
  ...overrides,
})

describe('optionImpliedBadge', () => {
  it('maps regime labels to red/blue/slate tones', () => {
    expect(optionImpliedBadge(block({ regime: '恐慌' }))).toMatchObject({ label: '恐慌', bg: 'bg-red-100' })
    expect(optionImpliedBadge(block({ regime: '自满' }))).toMatchObject({ label: '自满', bg: 'bg-sky-100' })
    expect(optionImpliedBadge(block({ regime: '中性' }))).toMatchObject({ label: '中性', bg: 'bg-slate-100' })
  })
  it('falls back to amber 数据不足 when status is insufficient_data', () => {
    expect(optionImpliedBadge(block({ status: 'insufficient_data', regime: null }))).toEqual({
      bg: 'bg-amber-100',
      color: 'text-amber-700',
      label: '数据不足',
    })
  })
  it('treats an ok status with a null regime as 数据不足 — never fabricates 中性', () => {
    expect(optionImpliedBadge(block({ status: 'ok', regime: null })).label).toBe('数据不足')
  })
  it('uses slate for an unknown regime string', () => {
    expect(optionImpliedBadge(block({ regime: '未知' })).bg).toBe('bg-slate-100')
  })
})

describe('hasOptionImpliedContent', () => {
  it('renders for an ok regime', () => {
    expect(hasOptionImpliedContent(block())).toBe(true)
  })
  it('renders when any single metric row is present, even without a regime', () => {
    expect(hasOptionImpliedContent(block({ status: 'insufficient_data', regime: null, qvix: { current: 25.8, as_of: '2026-09-29', percentile_1y: null, history_days: 250 } }))).toBe(true)
    expect(hasOptionImpliedContent(block({ status: 'insufficient_data', regime: null, pcr: { market_pcr: 0.85, by_underlying: {} } }))).toBe(true)
  })
  it('renders nothing when regime and every metric are null/absent', () => {
    expect(
      hasOptionImpliedContent(
        block({ status: 'insufficient_data', regime: null, iv: { status: 'no_contracts', atm_iv_near: null, near_expiry: null, atm_iv_next: null, next_expiry: null, term_structure: null, skew_25d: null, n_contracts: 0, n_filtered: 0 } })
      )
    ).toBe(false)
  })
})

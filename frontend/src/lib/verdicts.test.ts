// Regression pins for the statistical verdict tiers. These functions decide
// when a measurement-chain result is labeled 显著 / 帮倒忙 / 与噪音不可区分 —
// a flipped tier mislabels statistical evidence. Extracted verbatim from
// BacktestForm (null benchmark), WalkForwardForm (DSR), CalibrationForm
// (Wilson floor) and the monitoring page (provider health) in iteration 126;
// the pins lock CURRENT behavior, boundaries included.
import { describe, it, expect } from 'vitest'
import {
  nullBenchmarkVerdict,
  deflatedSharpeVerdict,
  calibrationVerdict,
  providerTone,
} from '@/lib/verdicts'

const EMERALD = 'text-emerald-600 dark:text-emerald-400'
const RED = 'text-red-500'
const AMBER = 'text-amber-600 dark:text-amber-400'

describe('nullBenchmarkVerdict', () => {
  it('labels p ≤ 0.05 as significantly better than random (boundary inclusive)', () => {
    expect(nullBenchmarkVerdict(0.05)).toEqual({
      text: '信号显著优于随机入场（p ≤ 0.05）',
      cls: EMERALD,
    })
    expect(nullBenchmarkVerdict(0.01).cls).toBe(EMERALD)
  })
  it('labels p ≥ 0.95 as an anti-signal — timing hurts (boundary inclusive)', () => {
    expect(nullBenchmarkVerdict(0.95).cls).toBe(RED)
    expect(nullBenchmarkVerdict(0.99).cls).toBe(RED)
  })
  it('keeps the middle band honest — indistinguishable from random timing', () => {
    expect(nullBenchmarkVerdict(0.5).cls).toBe(AMBER)
    expect(nullBenchmarkVerdict(0.94).cls).toBe(AMBER)
    expect(nullBenchmarkVerdict(0.06).cls).toBe(AMBER)
  })
})

describe('deflatedSharpeVerdict', () => {
  it('labels DSR ≥ 0.95 as surviving the selection-bias discount (boundary inclusive)', () => {
    expect(deflatedSharpeVerdict(0.95).cls).toBe(EMERALD)
    expect(deflatedSharpeVerdict(0.99).cls).toBe(EMERALD)
  })
  it('labels DSR ≤ 0.05 as a search survivor (boundary inclusive)', () => {
    expect(deflatedSharpeVerdict(0.05).cls).toBe(RED)
    expect(deflatedSharpeVerdict(0.01).cls).toBe(RED)
  })
  it('keeps the middle band honest — cannot beat selection noise yet', () => {
    expect(deflatedSharpeVerdict(0.5).cls).toBe(AMBER)
    expect(deflatedSharpeVerdict(0.949).cls).toBe(AMBER)
    expect(deflatedSharpeVerdict(0.06).cls).toBe(AMBER)
  })
})

describe('calibrationVerdict', () => {
  it('reports 无成熟事件 when hit_rate is null', () => {
    expect(calibrationVerdict(null, null)).toEqual({ text: '无成熟事件', cls: AMBER })
    expect(calibrationVerdict(null, 0.7).text).toBe('无成熟事件')
  })
  it('confirms the edge only when the Wilson lower bound is strictly above 0.5', () => {
    expect(calibrationVerdict(0.7, 0.55).cls).toBe(EMERALD)
    // Exactly 0.5 is NOT > 0.5 — the strict comparison is the whole point of
    // a conservative floor: a boundary-bound estimate stays inconclusive.
    expect(calibrationVerdict(0.7, 0.5).cls).toBe(AMBER)
  })
  it('labels sub-half hit rates red even before Wilson is considered', () => {
    expect(calibrationVerdict(0.45, 0.3).cls).toBe(RED)
  })
  it('keeps hit ≥ 0.5 without a confirming bound amber — sample not yet conclusive', () => {
    expect(calibrationVerdict(0.6, null).cls).toBe(AMBER)
    expect(calibrationVerdict(0.5, 0.4).cls).toBe(AMBER)
  })
})

describe('providerTone', () => {
  it('is healthy whenever fail === 0 (vacuously healthy with no outcomes)', () => {
    expect(providerTone({ ok: 3, fallback: 1, fail: 0 })).toBe('healthy')
    expect(providerTone({ ok: 0, fallback: 0, fail: 0 })).toBe('healthy')
  })
  it('is down only when every recorded outcome failed', () => {
    expect(providerTone({ ok: 0, fallback: 0, fail: 5 })).toBe('down')
  })
  it('is degraded when failures coexist with any surviving outcome', () => {
    expect(providerTone({ ok: 2, fallback: 0, fail: 1 })).toBe('degraded')
    // fallback counts as survival — the fallback chain caught the failures.
    expect(providerTone({ ok: 0, fallback: 2, fail: 3 })).toBe('degraded')
  })
})

// Regression pins for the money/currency formatters. These functions were
// module-private in result/page.tsx for 30+ frontend iterations with only
// tsc/lint/build watching them — the currency-inference rules mirror the
// backend's _liquidity_block semantics and are the highest-stakes pure
// logic in the UI (a wrong symbol renders A-share prices as dollars).
// The tests pin CURRENT behavior; changing an output is a visible decision.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  formatNumber,
  formatPercent,
  formatAdv,
  formatCurrency,
  currencyForSymbol,
  formatMarketCap,
  sparkColor,
  formatSignedPercent,
  relativeTime,
} from '@/lib/format'

describe('formatNumber', () => {
  it('formats with 2 decimals by default', () => {
    expect(formatNumber(12.3456)).toBe('12.35')
  })
  it('honors a custom decimal count', () => {
    expect(formatNumber(3.14159, 3)).toBe('3.142')
  })
  it('returns - for undefined and NaN', () => {
    expect(formatNumber(undefined)).toBe('-')
    expect(formatNumber(NaN)).toBe('-')
  })
})

describe('formatPercent', () => {
  it('scales a 0-1 ratio with one decimal', () => {
    expect(formatPercent(0.31)).toBe('31.0%')
  })
  it('keeps the sign for drawdown/VaR style negatives', () => {
    expect(formatPercent(-0.056)).toBe('-5.6%')
  })
  it('treats 0 as a real value, not missing', () => {
    expect(formatPercent(0, 0)).toBe('0%')
  })
  it('returns - for null and undefined', () => {
    expect(formatPercent(null)).toBe('-')
    expect(formatPercent(undefined)).toBe('-')
  })
})

describe('formatAdv', () => {
  it('renders CNY turnover in 万 (万-scaling is absolute, no B branch)', () => {
    expect(formatAdv(1_500_000, 'CNY')).toBe('150万')
    // CNY takes precedence over the >=1e9 B branch — pinned as-is.
    expect(formatAdv(2.5e9, 'CNY')).toBe('250000万')
  })
  it('rounds 万 to whole units', () => {
    expect(formatAdv(999_999, 'CNY')).toBe('100万')
  })
  it('renders USD turnover as M below 1e9 and B above', () => {
    expect(formatAdv(1_500_000, 'USD')).toBe('1.5M')
    expect(formatAdv(2.5e9, 'USD')).toBe('2.5B')
  })
  it('returns - for null', () => {
    expect(formatAdv(null, 'CNY')).toBe('-')
  })
})

describe('formatCurrency', () => {
  it('maps currency codes to symbols', () => {
    expect(formatCurrency(12.5, 'CNY')).toBe('¥12.50')
    expect(formatCurrency(99.2, 'HKD')).toBe('HK$99.20')
    expect(formatCurrency(3.1)).toBe('$3.10')
    expect(formatCurrency(3.1, 'USD')).toBe('$3.10')
  })
  it('returns - for undefined', () => {
    expect(formatCurrency(undefined, 'CNY')).toBe('-')
  })
})

describe('currencyForSymbol', () => {
  it('infers CNY from a bare 6-digit A-share code', () => {
    expect(currencyForSymbol('600000')).toBe('CNY')
    expect(currencyForSymbol('002415')).toBe('CNY')
  })
  it('infers HKD from .HK suffixes, case-insensitively', () => {
    expect(currencyForSymbol('00700.HK')).toBe('HKD')
    expect(currencyForSymbol('0700.hk')).toBe('HKD')
  })
  it('defaults to USD for US tickers', () => {
    expect(currencyForSymbol('AAPL')).toBe('USD')
  })
  it('falls back to USD for suffixed symbols — the 6-digit rule is exact (mirrors backend)', () => {
    // 000001.SS is an index feed symbol, not a tradable A-share code; the
    // strict regex keeps it out of the CNY branch, same as _liquidity_block.
    expect(currencyForSymbol('000001.SS')).toBe('USD')
  })
})

describe('formatMarketCap', () => {
  it('renders CNY market cap in 亿', () => {
    expect(formatMarketCap(2.5e9, 'CNY')).toBe('¥25亿')
  })
  it('renders USD market cap in B below a trillion', () => {
    expect(formatMarketCap(1.23e9, 'USD')).toBe('$1.23B')
    expect(formatMarketCap(9.99e11)).toBe('$999.00B')
  })
  it('switches to T at 1e12', () => {
    expect(formatMarketCap(1.5e12)).toBe('$1.50T')
  })
  it('returns - for null', () => {
    expect(formatMarketCap(null, 'CNY')).toBe('-')
  })
})

describe('sparkColor', () => {
  it('colors both bullish tiers emerald', () => {
    expect(sparkColor('bullish')).toBe('#10b981')
    expect(sparkColor('strong_bullish')).toBe('#10b981')
  })
  it('colors both bearish tiers red', () => {
    expect(sparkColor('bearish')).toBe('#ef4444')
    expect(sparkColor('strong_bearish')).toBe('#ef4444')
  })
  it('defaults neutral and unknown trends to slate', () => {
    expect(sparkColor('neutral')).toBe('#94a3b8')
    expect(sparkColor(undefined)).toBe('#94a3b8')
  })
})

describe('formatSignedPercent', () => {
  it('prefixes non-negative values with +', () => {
    expect(formatSignedPercent(0.312)).toBe('+31.2%')
  })
  it('keeps the minus sign for negatives', () => {
    expect(formatSignedPercent(-0.056)).toBe('-5.6%')
  })
  it('treats exactly zero as non-negative (+0.0%), pinned as-is', () => {
    expect(formatSignedPercent(0)).toBe('+0.0%')
  })
  it('honors a custom digit count', () => {
    expect(formatSignedPercent(0.5, 0)).toBe('+50%')
  })
})

describe('relativeTime', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-29T00:00:00Z'))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders sub-minute ages in seconds', () => {
    expect(relativeTime(new Date('2026-09-29T00:00:00Z').toISOString())).toBe('0 秒前')
    expect(relativeTime(new Date('2026-09-28T23:59:30Z').toISOString())).toBe('30 秒前')
  })
  it('switches to minutes at 60 seconds', () => {
    expect(relativeTime(new Date('2026-09-28T23:59:00Z').toISOString())).toBe('1 分钟前')
    // 59.999s floors to 59 — the band is [0, 60) in whole seconds.
    expect(relativeTime(new Date('2026-09-28T23:59:00.001Z').toISOString())).toBe('59 秒前')
  })
  it('switches to hours at 60 minutes', () => {
    expect(relativeTime(new Date('2026-09-28T23:00:00Z').toISOString())).toBe('1 小时前')
    // 59:59 stays in minutes.
    expect(relativeTime(new Date('2026-09-28T23:00:01Z').toISOString())).toBe('59 分钟前')
  })
  it('accumulates hours without switching to days', () => {
    expect(relativeTime(new Date('2026-09-28T00:00:00Z').toISOString())).toBe('24 小时前')
  })
  it('clamps future timestamps to 0 秒前 instead of negative ages', () => {
    expect(relativeTime(new Date('2026-09-29T00:00:30Z').toISOString())).toBe('0 秒前')
  })
  it('returns null for missing or unparseable timestamps', () => {
    expect(relativeTime(null)).toBeNull()
    expect(relativeTime('')).toBeNull()
    expect(relativeTime('not-a-date')).toBeNull()
  })
})

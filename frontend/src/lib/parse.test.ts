import { describe, expect, it } from 'vitest'

import {
  parseIntField,
  parseNumberField,
  parseNumberList,
  requireIntField,
  requireNumberField,
} from './parse'

describe('parseNumberList — comma-separated numeric grids (walk-forward param_grid)', () => {
  it('parses a clean list with surrounding spaces', () => {
    expect(parseNumberList('5, 10, 20')).toEqual([5, 10, 20])
  })

  it('keeps float members and drops empty segments (trailing/double commas)', () => {
    // Current form semantics pinned: empty segments are filtered, not fatal.
    expect(parseNumberList(' 3.5 ,, 7, ')).toEqual([3.5, 7])
  })

  it('accepts scientific notation members', () => {
    expect(parseNumberList('1e2, 5')).toEqual([100, 5])
  })

  it('returns null when any member is not a finite number', () => {
    expect(parseNumberList('5, x, 10')).toBeNull()
    expect(parseNumberList('5, NaN')).toBeNull()
    expect(parseNumberList('5, Infinity')).toBeNull()
  })

  it('returns null for an all-empty input (cleared field)', () => {
    expect(parseNumberList('')).toBeNull()
    expect(parseNumberList(' , , ')).toBeNull()
  })
})

describe('parseIntField — single integer fields (bars, periods)', () => {
  it('parses a clean integer with surrounding spaces', () => {
    expect(parseIntField(' 75 ')).toBe(75)
  })

  it('truncates decimals like parseInt (75.5 -> 75, pinned)', () => {
    // Bars are integers; preserving parseInt truncation keeps well-formed
    // input's behavior identical to the old inline calls.
    expect(parseIntField('75.5')).toBe(75)
  })

  it('returns null for cleared or non-numeric input', () => {
    expect(parseIntField('')).toBeNull()
    expect(parseIntField('   ')).toBeNull()
    expect(parseIntField('abc')).toBeNull()
  })
})

describe('parseNumberField — single numeric fields (cash, thresholds)', () => {
  it('parses clean integers and decimals', () => {
    expect(parseNumberField('10000')).toBe(10000)
    expect(parseNumberField(' 3.5 ')).toBe(3.5)
    expect(parseNumberField('-12.75')).toBe(-12.75)
  })

  it('returns null for a cleared field — Number("") is 0, not NaN', () => {
    // The exact footgun this guard exists for: without it a cleared cash
    // field would submit 0 instead of erroring.
    expect(parseNumberField('')).toBeNull()
    expect(parseNumberField('   ')).toBeNull()
  })

  it('rejects comma-grouped numbers instead of silently truncating', () => {
    // Strictness improvement over parseFloat: "10,000" would have become 10
    // dollars on the wire; now it is a validation error.
    expect(parseNumberField('10,000')).toBeNull()
  })

  it('returns null for non-numeric input', () => {
    expect(parseNumberField('abc')).toBeNull()
    expect(parseNumberField('1.2.3')).toBeNull()
  })
})

describe('require*Field — throwing wrappers for form submit handlers', () => {
  it('requireIntField returns the value and names the field on error', () => {
    expect(requireIntField('train_bars', '360')).toBe(360)
    expect(() => requireIntField('train_bars', '')).toThrowError(
      '参数 train_bars 无效——请输入整数',
    )
  })

  it('requireNumberField returns the value and names the field on error', () => {
    expect(requireNumberField('initial_cash', '10000')).toBe(10000)
    expect(() => requireNumberField('initial_cash', '1.2.3')).toThrowError(
      '参数 initial_cash 无效——请输入数字',
    )
  })
})

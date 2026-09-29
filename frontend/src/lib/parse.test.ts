import { describe, expect, it } from 'vitest'

import {
  parseDateField,
  parseIntField,
  parseNonEmptyText,
  parseNumberField,
  parseNumberList,
  requireDateField,
  requireDateOrder,
  requireIntField,
  requireNonEmptyText,
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

describe('parseNonEmptyText — text fields (symbol)', () => {
  it('returns the trimmed value for clean and padded input', () => {
    expect(parseNonEmptyText('AAPL')).toBe('AAPL')
    expect(parseNonEmptyText('  600000 ')).toBe('600000')
  })

  it('returns null for cleared or whitespace-only input', () => {
    // Before this guard all three backtest forms sent bare
    // symbol.toUpperCase() — a cleared field shipped "" and the failure
    // surfaced as pydantic's English 422, bypassing the form's error box.
    expect(parseNonEmptyText('')).toBeNull()
    expect(parseNonEmptyText('   ')).toBeNull()
  })
})

describe('requireNonEmptyText — throwing wrapper for the symbol field', () => {
  it('returns the trimmed value and names the field on error', () => {
    expect(requireNonEmptyText('股票代码', ' 600519 ')).toBe('600519')
    expect(() => requireNonEmptyText('股票代码', '  ')).toThrowError('参数 股票代码 不能为空')
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

describe('parseDateField — date fields (start/end date, type="date" inputs)', () => {
  it('returns the trimmed value for a well-formed calendar date', () => {
    expect(parseDateField('2023-01-01')).toBe('2023-01-01')
    expect(parseDateField('  2024-06-15  ')).toBe('2024-06-15')
    // Leap-year day is a real date.
    expect(parseDateField('2024-02-29')).toBe('2024-02-29')
  })

  it('returns null for a cleared or whitespace-only field', () => {
    // The realistic garbage from a type="date" input is "" (cleared);
    // the browser enforces the shape, this guard catches the clearing.
    expect(parseDateField('')).toBeNull()
    expect(parseDateField('   ')).toBeNull()
  })

  it('returns null for malformed shapes the wire contract rejects', () => {
    expect(parseDateField('2023/01/01')).toBeNull()
    expect(parseDateField('23-01-01')).toBeNull()
    expect(parseDateField('2023-1-1')).toBeNull()
    expect(parseDateField('not-a-date')).toBeNull()
  })

  it('returns null for calendar-impossible dates that match the shape', () => {
    // 2023-02-30 matches ^\d{4}-\d{2}-\d{2}$ but Date rolls it to March —
    // the round-trip check catches what the regex cannot.
    expect(parseDateField('2023-02-30')).toBeNull()
    expect(parseDateField('2023-13-01')).toBeNull()
    expect(parseDateField('2023-00-10')).toBeNull()
    expect(parseDateField('2023-02-29')).toBeNull() // 2023 is not a leap year
  })
})

describe('requireDateField — throwing wrapper for the date fields', () => {
  it('returns the value and names the field on error', () => {
    expect(requireDateField('开始日期', '2023-01-01')).toBe('2023-01-01')
    expect(() => requireDateField('开始日期', '')).toThrowError(
      '参数 开始日期 无效——请输入日期',
    )
    expect(() => requireDateField('结束日期', '2023-02-30')).toThrowError(
      '参数 结束日期 无效——请输入日期',
    )
  })
})

describe('requireDateOrder — cross-field guard for date pairs', () => {
  it('passes silently for a well-ordered range', () => {
    // Adjacent days are the narrowest legal range (same-day is rejected,
    // mirroring the backend's end <= start rule).
    expect(() => requireDateOrder('2023-01-01', '2023-01-02')).not.toThrow()
    expect(() => requireDateOrder('2023-01-01', '2024-01-01')).not.toThrow()
  })

  it('throws for a same-day range — end <= start, mirroring the backend', () => {
    expect(() => requireDateOrder('2023-01-01', '2023-01-01')).toThrowError(
      '日期区间无效——结束日期必须晚于开始日期',
    )
  })

  it('throws for a reversed range', () => {
    expect(() => requireDateOrder('2024-01-01', '2023-01-01')).toThrowError(
      '日期区间无效——结束日期必须晚于开始日期',
    )
  })
})

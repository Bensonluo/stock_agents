// Form-input parsing helpers shared by the three backtest forms.
//
// Before this module each form rolled its own conversion: CalibrationForm
// validated everything, WalkForwardForm validated the param grid but sent
// NaN for train_bars/test_bars/initial_cash, and BacktestForm validated
// nothing — a cleared number input hit parseInt("") -> NaN, which
// JSON.stringify renders as null and pydantic answers with a cryptic
// English 422 instead of the form's styled error channel.

/**
 * Parse a comma-separated numeric list ("5, 10, 20") for param grids.
 * Empty segments (trailing/double commas) are dropped; null means the list
 * is empty after filtering or any member is not a finite number.
 */
export function parseNumberList(raw: string): number[] | null {
  const values = raw
    .split(',')
    .map((s) => s.trim())
    .filter((s) => s.length > 0)
    .map(Number)
  if (values.length === 0 || values.some((v) => !Number.isFinite(v))) return null
  return values
}

/**
 * Parse a single integer field (bars, periods). Preserves parseInt
 * truncation semantics ("75.5" -> 75); null for cleared/non-numeric input.
 */
export function parseIntField(raw: string): number | null {
  const value = parseInt(raw.trim(), 10)
  return Number.isFinite(value) ? value : null
}

/**
 * Parse a single numeric field (cash, thresholds). Deliberately stricter
 * than parseFloat: "" -> null (Number("") is 0, the cleared-field footgun)
 * and "10,000" -> null (parseFloat would silently send 10).
 */
export function parseNumberField(raw: string): number | null {
  const trimmed = raw.trim()
  if (trimmed.length === 0) return null
  const value = Number(trimmed)
  return Number.isFinite(value) ? value : null
}

/**
 * Parse a text field (symbol). Returns the trimmed value; null for a
 * cleared or whitespace-only field. Whitespace-only symbols previously
 * shipped verbatim (" " is truthy) and died server-side.
 */
export function parseNonEmptyText(raw: string): string | null {
  const trimmed = raw.trim()
  return trimmed.length > 0 ? trimmed : null
}

/** Throwing wrapper for submit handlers — names the field in the error. */
export function requireIntField(label: string, raw: string): number {
  const value = parseIntField(raw)
  if (value === null) throw new Error(`参数 ${label} 无效——请输入整数`)
  return value
}

/** Throwing wrapper for submit handlers — names the field in the error. */
export function requireNumberField(label: string, raw: string): number {
  const value = parseNumberField(raw)
  if (value === null) throw new Error(`参数 ${label} 无效——请输入数字`)
  return value
}

/** Throwing wrapper for submit handlers — names the field in the error. */
export function requireNonEmptyText(label: string, raw: string): string {
  const value = parseNonEmptyText(raw)
  if (value === null) throw new Error(`参数 ${label} 不能为空`)
  return value
}

/**
 * Parse a date field (start/end date, type="date" inputs). Returns the
 * trimmed YYYY-MM-DD value; null for a cleared field, a malformed shape,
 * or a calendar-impossible date that matches the shape (2023-02-30 rolls
 * to March inside Date — the round-trip check catches what the regex
 * cannot). Mirrors the backend pattern ^\d{4}-\d{2}-\d{2}$ plus realness.
 */
export function parseDateField(raw: string): string | null {
  const trimmed = raw.trim()
  if (!/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) return null
  const [y, m, d] = trimmed.split('-').map(Number)
  const dt = new Date(Date.UTC(y, m - 1, d))
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) {
    return null
  }
  return trimmed
}

/** Throwing wrapper for submit handlers — names the field in the error. */
export function requireDateField(label: string, raw: string): string {
  const value = parseDateField(raw)
  if (value === null) throw new Error(`参数 ${label} 无效——请输入日期`)
  return value
}

/**
 * Cross-field guard for date pairs (start/end). YYYY-MM-DD strings compare
 * lexicographically in chronological order, so a plain string comparison
 * mirrors the backend's end <= start rejection exactly (same-day ranges
 * are rejected there too). Call after both fields pass requireDateField.
 */
export function requireDateOrder(start: string, end: string): void {
  if (end <= start) {
    throw new Error('日期区间无效——结束日期必须晚于开始日期')
  }
}

/**
 * Cross-field guard for strategy parameter pairs (short/long, oversold/
 * overbought, fast/slow). Mirrors the V1 backend model's rejection of
 * less >= more — equality included: sma_short == sma_long is rejected
 * there, so the client guard must reject it too. Call after both fields
 * pass their parse/require wrapper.
 */
export function requireLessThan(
  lessLabel: string,
  moreLabel: string,
  less: number,
  more: number,
): void {
  if (less >= more) {
    throw new Error(`参数 ${lessLabel} 必须小于 ${moreLabel}`)
  }
}

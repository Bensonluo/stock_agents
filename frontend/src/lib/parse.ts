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

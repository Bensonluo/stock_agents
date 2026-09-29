// Pure formatting helpers shared by the result page. Extracted verbatim
// from app/result/page.tsx (iteration 125) so they can be regression-tested
// — these encode the money/currency semantics mirrored from the backend's
// _liquidity_block / market-cap conventions.

// 格式化数字
export function formatNumber(num: number | undefined, decimals = 2): string {
  if (num === undefined || num === null || isNaN(num as number)) return '-'
  return (num as number).toFixed(decimals)
}

// 格式化比率（0.31 → "31.0%"；VaR/回撤为负值原样带符号）
export function formatPercent(num: number | undefined | null, decimals = 1): string {
  if (num === undefined || num === null || isNaN(num)) return '-'
  return `${(num * 100).toFixed(decimals)}%`
}

// 格式化成交额（按币种本地化缩写：1500000 → "150万" / "1.5M"）
export function formatAdv(num: number | undefined | null, currency: string): string {
  if (num === undefined || num === null || isNaN(num)) return '-'
  if (currency === 'CNY') return `${(num / 10000).toFixed(0)}万`
  if (num >= 1e9) return `${(num / 1e9).toFixed(1)}B`
  return `${(num / 1e6).toFixed(1)}M`
}

// 格式化货币（CNY → ¥，HKD → HK$，其余 $）
export function formatCurrency(num: number | undefined, currency?: string): string {
  if (num === undefined || num === null || isNaN(num)) return '-'
  const symbol = currency === 'CNY' ? '¥' : currency === 'HKD' ? 'HK$' : '$'
  return `${symbol}${num.toFixed(2)}`
}

// 按标的推断币种（镜像后端 _liquidity_block 语义）：6 位数字 → CNY，
// .HK → HKD，其余 USD。仅在 overview 未带 currency 时兜底。
export function currencyForSymbol(symbol: string): string {
  if (symbol.toUpperCase().includes('.HK')) return 'HKD'
  if (/^\d{6}$/.test(symbol)) return 'CNY'
  return 'USD'
}

// 格式化市值（CNY 按亿，USD 按 B —— A 股市值以亿计是本土惯例）
export function formatMarketCap(num: number | undefined | null, currency?: string): string {
  if (num === undefined || num === null || isNaN(num)) return '-'
  if (currency === 'CNY') return `¥${(num / 1e8).toFixed(0)}亿`
  if (num >= 1e12) return `$${(num / 1e12).toFixed(2)}T`
  return `$${(num / 1e9).toFixed(2)}B`
}

// Sparkline 线色（SVG hex，趋势同色系：emerald-500 / red-500 / slate-400）
export function sparkColor(trend: string | undefined): string {
  if (trend === 'bullish' || trend === 'strong_bullish') return '#10b981'
  if (trend === 'bearish' || trend === 'strong_bearish') return '#ef4444'
  return '#94a3b8'
}

// 带符号百分比（回测三表单共用：+31.2% / -5.6%；0 按 + 计——pinned as-is）
export function formatSignedPercent(value: number, digits = 1): string {
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(digits)}%`
}

// 统计值格式化（SignalQualityCard 指标瓦片/行共用，iteration 129 逐字提取）：
// 缺数渲染 em dash「—」——该卡指标位的既定风格，与金额类的 "-" 是两种页面
// 惯例，各自保真；NaN 落「—」同本文件 honest-guard 约定（wire 上不会出现）。
export function formatStat(value: number | null | undefined, digits = 3): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—'
  return value.toFixed(digits)
}

// 相对时间（monitoring 页：秒/分钟/小时三档；未来时间戳钳到 0 秒，无效输入 → null）
export function relativeTime(iso: string | null): string | null {
  if (!iso) return null
  const ms = Date.now() - new Date(iso).getTime()
  if (Number.isNaN(ms)) return null
  const seconds = Math.max(0, Math.floor(ms / 1000))
  if (seconds < 60) return `${seconds} 秒前`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} 分钟前`
  return `${Math.floor(minutes / 60)} 小时前`
}

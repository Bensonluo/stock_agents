// Shared error-message extraction for the API client's !response.ok
// branches (iteration 142).
//
// The backend speaks two error dialects and the client must read both:
// - HTTPException(status, "message") → { detail: "message" } (string) —
//   engine semantic rejections mapped to 422, service-layer errors.
// - pydantic v2 validation failures → { detail: [{type, loc, msg}, ...] }
//   (array) — model-level constraint violations.
// Before this module the client's methods each picked their own subset of
// that contract (most threw a generic English string discarding the body,
// the rest only read string details), so backend rejections surfaced in
// form error boxes as opaque 'Backtest failed'-style messages.

function extractDetailMessages(detail: unknown): string[] {
  if (!Array.isArray(detail)) return []
  const messages: string[] = []
  for (const member of detail) {
    if (member && typeof member === 'object' && 'msg' in member) {
      const msg = (member as { msg: unknown }).msg
      if (typeof msg === 'string' && msg.length > 0) messages.push(msg)
    }
  }
  return messages
}

/**
 * Extract the most informative message a failed response can offer:
 * gate statuses (429/503) → friendly Chinese copy with the Retry-After
 * wait → string detail → pydantic array-detail msgs joined with '; ' →
 * body.message → `${fallback} (HTTP ${status})` when the body says
 * nothing usable (including non-JSON bodies, e.g. a proxy's empty 502).
 */
export async function apiErrorMessage(response: Response, fallback: string): Promise<string> {
  // The resilience gates answer with English one-liners (rate limiter 429
  // since iteration 169, capacity gate 503 since iteration 170). The UI is
  // Chinese — map these two statuses to friendly copy instead of relaying
  // the raw detail, carrying the Retry-After wait when the header is usable.
  if (response.status === 429) {
    const wait = Number(response.headers.get('retry-after'))
    return Number.isFinite(wait) && wait > 0
      ? `请求过于频繁,请 ${wait} 秒后再试`
      : '请求过于频繁,请稍后再试'
  }
  if (response.status === 503) {
    return '服务器繁忙,请稍后再试'
  }

  let body: unknown
  try {
    body = await response.json()
  } catch {
    body = null
  }
  if (body !== null && typeof body === 'object') {
    const { detail, message } = body as { detail?: unknown; message?: unknown }
    if (typeof detail === 'string' && detail.length > 0) return detail
    const detailMessages = extractDetailMessages(detail)
    if (detailMessages.length > 0) return detailMessages.join('; ')
    if (typeof message === 'string' && message.length > 0) return message
  }
  return `${fallback} (HTTP ${response.status})`
}

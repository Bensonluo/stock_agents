// Locks the API client's error-propagation contract (iteration 142).
//
// Before this, the client's !response.ok branches split into three tiers:
// some methods parsed a string `detail` from the body, most threw a generic
// English string ('Backtest failed') that discarded whatever the server
// said, and none handled pydantic 422 bodies where `detail` is an ARRAY of
// {loc, msg} objects — so a backend semantic rejection (engine ValueError
// mapped to 422, model-validation failure) surfaced in form error boxes as
// an opaque generic string. apiErrorMessage unifies every branch; the
// wiring tests pin that the real client methods now surface the message.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiErrorMessage } from './api-error'
import { API } from '@/lib/utils'

function jsonResponse(body: unknown, status = 422): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('apiErrorMessage', () => {
  it('returns a string detail verbatim', async () => {
    const msg = await apiErrorMessage(
      jsonResponse({ detail: 'Not enough data for the requested window' }, 422),
      'Backtest failed',
    )
    expect(msg).toBe('Not enough data for the requested window')
  })

  it('joins pydantic array-detail member messages (422 model validation)', async () => {
    // FastAPI/pydantic v2 validation errors: detail is a list of
    // {type, loc, msg, input} objects, not a string.
    const body = {
      detail: [
        { type: 'value_error', loc: ['body', 'end_date'], msg: 'Value error, End date must be after start date' },
        { type: 'missing', loc: ['body', 'symbol'], msg: 'Field required' },
      ],
    }
    const msg = await apiErrorMessage(jsonResponse(body), 'Backtest failed')
    expect(msg).toBe('Value error, End date must be after start date; Field required')
  })

  it('falls back when array detail carries no string messages', async () => {
    const msg = await apiErrorMessage(
      jsonResponse({ detail: [{ loc: ['body'] }] }),
      'Backtest failed',
    )
    expect(msg).toBe('Backtest failed (HTTP 422)')
  })

  it('falls back on an empty detail array', async () => {
    expect(await apiErrorMessage(jsonResponse({ detail: [] }), 'Backtest failed')).toBe(
      'Backtest failed (HTTP 422)',
    )
  })

  it('falls back when detail is an empty string', async () => {
    expect(await apiErrorMessage(jsonResponse({ detail: '' }), 'Backtest failed')).toBe(
      'Backtest failed (HTTP 422)',
    )
  })

  it('falls back when detail is a non-string scalar', async () => {
    expect(await apiErrorMessage(jsonResponse({ detail: 42 }), 'Backtest failed')).toBe(
      'Backtest failed (HTTP 422)',
    )
  })

  it('returns body.message when detail is absent', async () => {
    const msg = await apiErrorMessage(jsonResponse({ message: 'upstream said no' }, 500), 'failed')
    expect(msg).toBe('upstream said no')
  })

  it('falls back naming the operation and status when the body is not JSON', async () => {
    const response = new Response('Bad Gateway', { status: 502 })
    expect(await apiErrorMessage(response, 'Sync analysis failed')).toBe(
      'Sync analysis failed (HTTP 502)',
    )
  })
})

describe('API error propagation (wiring)', () => {
  it('runBacktest surfaces the backend 422 detail instead of a generic string', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({ detail: 'Not enough historical data for the requested window' }, 422),
      ),
    )
    await expect(
      API.runBacktest({
        symbol: 'AAPL',
        strategy: 'sma_crossover',
        start_date: '2023-01-01',
        end_date: '2024-01-01',
      }),
    ).rejects.toThrow('Not enough historical data for the requested window')
  })

  it('getStrategies surfaces a string detail from a 500', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ detail: 'strategy registry unavailable' }, 500)),
    )
    await expect(API.getStrategies()).rejects.toThrow('strategy registry unavailable')
  })

  it('analyzeSync names the operation and status when the body is unparseable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 502 })))
    await expect(API.analyzeSync({ query: 'q', symbols: ['AAPL'] })).rejects.toThrow(
      'Sync analysis failed (HTTP 502)',
    )
  })
})

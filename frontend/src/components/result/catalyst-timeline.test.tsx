// @vitest-environment jsdom
// Component-level pins for CatalystTimeline — the CN-native catalyst feed
// (同花顺 F10 公司大事 style) consumed from report.sections.catalysts.
// by_symbol[symbol]. Locks what lands in the DOM: the pinned 下一个催化剂
// card with the prominent days_until, the bucket-grouped vertical feed
// (更远 collapsed by default), the 近四季 EPS 预期差 mini-table with its
// green/red surprise color routing, and the honest-absence gate (old
// reports without the key, or a symbol with no events AND empty surprise,
// render NOTHING). Pure helpers (sortEvents / groupByBucket / nextEventOf /
// detailLineOf / daysUntilZh) are asserted alongside their DOM wiring.
// No '@/lib/utils' mock needed: CatalystTimeline reads no API methods, and
// the real cn() import has no side effects.
import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CatalystTimeline, detailLineOf, daysUntilZh, groupByBucket, nextEventOf, sortEvents } from './CatalystTimeline'
import { ReactReport } from './ReactReport'
import type { CatalystEvent, SymbolCatalysts } from './types'

// The ev fixture builder is deliberately wire-loose on type/bucket so the
// unknown-value fallback tests can send values outside the declared unions
// (exactly what a shape-drifted payload would do) without lying elsewhere.
const ev = (
  overrides: Partial<Omit<CatalystEvent, 'type' | 'bucket'>> & {
    date: string
    days_until: number
    type?: string
    bucket?: string
  }
): CatalystEvent =>
  ({
    bucket: '1w',
    type: 'earnings',
    title: '事件',
    ...overrides,
  }) as CatalystEvent

const fullCatalysts: SymbolCatalysts = {
  events: [
    // Wire order intentionally NOT ascending — sortEvents must fix it.
    ev({ date: '2026-12-15', days_until: 120, bucket: 'later', type: 'unlock', title: '大股东限售股解禁' }),
    ev({ date: '2026-12-11', days_until: 50, bucket: '3m', type: 'split', title: '资本公积转增股本' }),
    ev({
      date: '2026-10-28',
      days_until: 3,
      bucket: '1w',
      type: 'earnings',
      title: '2026年三季报发布',
      detail: { eps_hint: 0.45 },
    }),
    ev({
      date: '2026-11-14',
      days_until: 20,
      bucket: '1m',
      type: 'dividend',
      title: '季度分红除息',
      detail: { amount: 0.82, yield_pct: 1.2 },
    }),
  ],
  earnings_surprise: [
    { date: '2026-07-30', estimate: 2.0, actual: 2.25, surprise_pct: 12.5 },
    { date: '2026-04-29', estimate: 1.8, actual: 1.74, surprise_pct: -3.2 },
  ],
}

describe('CatalystTimeline (single symbol)', () => {
  it('pins the next event and renders the bucketed feed from a full fixture', () => {
    render(<CatalystTimeline symbol="AAPL" data={fullCatalysts} />)

    // Header carries the card title and the symbol badge.
    expect(screen.getByText('催化剂时间轴')).toBeInTheDocument()
    expect(screen.getByText('AAPL')).toBeInTheDocument()

    // Pinned next event: smallest days_until (3) wins, shown prominently.
    expect(screen.getByText('下一个催化剂')).toBeInTheDocument()
    expect(screen.getByText('3天后')).toBeInTheDocument()
    // The pinned title appears twice (pinned card + its 1w feed row) — and
    // ONLY the min-days event's title does.
    expect(screen.getAllByText('2026年三季报发布').length).toBe(2)
    expect(screen.getAllByText('EPS 参考 0.45').length).toBe(2)

    // Bucket headers in fixed order; rows carry date + chip + bold title.
    expect(screen.getByText('未来一周')).toBeInTheDocument()
    expect(screen.getByText('未来一月')).toBeInTheDocument()
    expect(screen.getByText('未来三月')).toBeInTheDocument()
    // The pinned event's date renders in both the pinned card and its row.
    expect(screen.getAllByText('2026-10-28').length).toBe(2)
    expect(screen.getByText('2026-11-14')).toBeInTheDocument()
    expect(screen.getByText('季度分红除息')).toBeInTheDocument()
    expect(screen.getByText('派息 $0.82 · 股息率 1.2%')).toBeInTheDocument()
    expect(screen.getByText('资本公积转增股本')).toBeInTheDocument()
    // 财报发布 chip = pinned block + 1w feed row.
    expect(screen.getAllByText('财报发布').length).toBe(2)
    expect(screen.getByText('除息/分红')).toBeInTheDocument()
    expect(screen.getByText('拆股/送转')).toBeInTheDocument()
  })

  it('collapses the 更远 bucket by default and expands it on toggle', () => {
    render(<CatalystTimeline symbol="AAPL" data={fullCatalysts} />)

    // 更远 header renders with its count, but its rows are NOT in the DOM.
    expect(screen.getByText(/更远 · 1 条/)).toBeInTheDocument()
    expect(screen.queryByText('大股东限售股解禁')).not.toBeInTheDocument()
    expect(screen.queryByText('限售解禁')).not.toBeInTheDocument()

    fireEvent.click(screen.getByText(/更远 · 1 条/))
    expect(screen.getByText('大股东限售股解禁')).toBeInTheDocument()
    expect(screen.getByText('限售解禁')).toBeInTheDocument()

    fireEvent.click(screen.getByText(/更远 · 1 条/))
    expect(screen.queryByText('大股东限售股解禁')).not.toBeInTheDocument()
  })

  it('renders the surprise table with green positive and red negative 偏差%', () => {
    render(<CatalystTimeline symbol="AAPL" data={fullCatalysts} />)

    expect(screen.getByText('近四季 EPS 预期差')).toBeInTheDocument()
    expect(screen.getByText('日期')).toBeInTheDocument()
    expect(screen.getByText('预期')).toBeInTheDocument()
    expect(screen.getByText('实际')).toBeInTheDocument()
    expect(screen.getByText('偏差%')).toBeInTheDocument()

    expect(screen.getByText('2.00')).toBeInTheDocument()
    expect(screen.getByText('2.25')).toBeInTheDocument()
    const pos = screen.getByText('+12.5%')
    expect(pos).toHaveClass('text-green-600')
    const neg = screen.getByText('-3.2%')
    expect(neg).toHaveClass('text-red-600')
  })

  it('renders nothing at all when the symbol has no events and empty surprise', () => {
    // Old reports lack sections.catalysts entirely (caller maps over an
    // empty by_symbol) — and a present-but-empty per-symbol entry must
    // also gate the whole card.
    for (const data of [undefined, null, {}, { events: [], earnings_surprise: [] }]) {
      const { container, unmount } = render(
        <CatalystTimeline symbol="AAPL" data={data as SymbolCatalysts} />
      )
      expect(container).toBeEmptyDOMElement()
      unmount()
    }
  })

  it('renders the surprise-only degraded shape: no pinned card, no feed, table only', () => {
    render(
      <CatalystTimeline
        symbol="600519"
        data={{ earnings_surprise: [{ date: '2026-08-02', estimate: 16.4, actual: 17.1, surprise_pct: 4.3 }] }}
      />
    )
    expect(screen.getByText('催化剂时间轴')).toBeInTheDocument()
    expect(screen.getByText('600519')).toBeInTheDocument()
    expect(screen.queryByText('下一个催化剂')).not.toBeInTheDocument()
    expect(screen.queryByText(/未来一周/)).not.toBeInTheDocument()
    expect(screen.getByText('近四季 EPS 预期差')).toBeInTheDocument()
    expect(screen.getByText('+4.3%')).toHaveClass('text-green-600')
  })

  it('shows 今天 for days_until 0 and falls back to 其他 chip for unknown types', () => {
    render(
      <CatalystTimeline
        symbol="600519"
        data={{
          events: [ev({ date: '2026-09-30', days_until: 0, bucket: '1w', type: 'shareholder_meeting', title: '临时股东大会' })],
        }}
      />
    )
    expect(screen.getByText('今天')).toBeInTheDocument()
    // Unknown wire type falls back to the slate 其他 chip — never a crash.
    // The chip (and the title) render twice: pinned card + its feed row.
    expect(screen.getAllByText('其他').length).toBe(2)
    expect(screen.getAllByText('临时股东大会').length).toBe(2)
  })
})

describe('CatalystTimeline pure helpers', () => {
  it('sortEvents orders by days_until, breaks ties by date, and drops junk rows', () => {
    const sorted = sortEvents(fullCatalysts.events as CatalystEvent[])
    expect(sorted.map((e) => e.days_until)).toEqual([3, 20, 50, 120])
    expect(
      sortEvents([
        ev({ date: '2026-10-30', days_until: 5, title: 'a' }),
        ev({ date: '2026-10-28', days_until: 5, title: 'b' }),
      ]).map((e) => e.title)
    ).toEqual(['b', 'a'])
    // Non-object / dateless rows are filtered, not fatal.
    expect(sortEvents([null as unknown as CatalystEvent, ev({ date: '2026-10-28', days_until: 1 })]).length).toBe(1)
    expect(sortEvents(undefined as unknown as CatalystEvent[])).toEqual([])
  })

  it('nextEventOf picks the smallest days_until', () => {
    expect(nextEventOf(fullCatalysts.events as CatalystEvent[])?.days_until).toBe(3)
    expect(nextEventOf([])).toBeNull()
  })

  it('groupByBucket clamps unknown buckets into 更远 and keeps fixed order', () => {
    const groups = groupByBucket([
      ev({ date: '2026-12-20', days_until: 200, bucket: 'century', type: 'other' }),
      ev({ date: '2026-11-14', days_until: 50, bucket: '3m', type: 'other' }),
      ev({ date: '2026-10-28', days_until: 3, bucket: '1w', type: 'other' }),
    ] as CatalystEvent[])
    expect(groups.map(([b]) => b)).toEqual(['1w', '3m', 'later'])
    expect(groups[2][1].length).toBe(1)
  })

  it('detailLineOf renders known keys and skips unknown / non-numeric ones', () => {
    expect(
      detailLineOf(
        {
          ...ev({ date: 'd', days_until: 1 }),
          // region simulates a shape-drifted wire detail (string value)
          detail: { shares: 1.2e8, pct_of_float: 2.3, region: 'CN' } as unknown as Record<string, number>,
        },
        '600519'
      )
    ).toBe('解禁 1.20亿股 · 占流通股 2.3%')
    expect(
      detailLineOf(
        { ...ev({ date: 'd', days_until: 1 }), detail: { region: 'CN' } as unknown as Record<string, number> },
        '600519'
      )
    ).toBeNull()
    expect(detailLineOf(ev({ date: 'd', days_until: 1 }), '600519')).toBeNull()
  })

  it('daysUntilZh maps 0/negative to 今天 and positive to N天后', () => {
    expect(daysUntilZh(0)).toBe('今天')
    expect(daysUntilZh(-2)).toBe('今天')
    expect(daysUntilZh(3)).toBe('3天后')
  })
})

/* ── ReactReport wiring ────────────────────────────────────────────
 * Pins the symbol-switcher reuse: catalysts symbols join the switcher
 * universe, 'all' renders one card per symbol, selecting a symbol keeps
 * only its card, and an old report without sections.catalysts renders
 * zero catalyst cards. The fixture carries ONLY the catalysts section —
 * no tech/fund sections — so no chart/markdown machinery mounts. */

const catalystReport = (withCatalysts: boolean): Record<string, any> => ({
  title: '多标的催化剂报告',
  sections: {
    ...(withCatalysts
      ? {
          catalysts: {
            by_symbol: {
              AAPL: {
                events: [ev({ date: '2026-10-28', days_until: 3, type: 'earnings', title: 'AAPL 财报发布' })],
                earnings_surprise: [],
              },
              MSFT: {
                events: [ev({ date: '2026-11-20', days_until: 26, bucket: '1m', type: 'dividend', title: 'MSFT 分红除息' })],
                earnings_surprise: [],
              },
            },
          },
        }
      : {}),
  },
})

describe('ReactReport catalyst wiring', () => {
  it('renders one card per symbol under 全部标的 and filters by the selected symbol', () => {
    render(<ReactReport answer="" report={catalystReport(true)} />)

    // Both cards render initially (activeSymbol = 'all'). Each event title
    // appears twice per card (pinned card + its feed row).
    expect(screen.getAllByText('催化剂时间轴').length).toBe(2)
    expect(screen.getAllByText('AAPL 财报发布').length).toBe(2)
    expect(screen.getAllByText('MSFT 分红除息').length).toBe(2)

    // Selecting AAPL via the existing switcher keeps only its card — the
    // catalyst section reuses the same filterEntries seam as every other card.
    fireEvent.click(screen.getByRole('button', { name: 'AAPL' }))
    expect(screen.getAllByText('催化剂时间轴').length).toBe(1)
    expect(screen.getAllByText('AAPL 财报发布').length).toBe(2)
    expect(screen.queryAllByText('MSFT 分红除息').length).toBe(0)

    // Back to 全部标的 restores both.
    fireEvent.click(screen.getByRole('button', { name: '全部标的' }))
    expect(screen.getAllByText('催化剂时间轴').length).toBe(2)
  })

  it('renders zero catalyst cards for an old report without sections.catalysts', () => {
    render(<ReactReport answer="" report={catalystReport(false)} />)
    expect(screen.queryByText('催化剂时间轴')).not.toBeInTheDocument()
    expect(screen.queryByText('下一个催化剂')).not.toBeInTheDocument()
    // The report itself still renders (title present), not a crash page.
    expect(screen.getByText('多标的催化剂报告')).toBeInTheDocument()
  })
})

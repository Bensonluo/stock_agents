// @vitest-environment jsdom
// Component-level lock for the input-validation wiring (iterations 136-137):
// a cleared numeric field must block submit with the form's field-named
// Chinese error instead of sending NaN (rendered as null on the wire and
// answered by pydantic's English 422); a cleared symbol must likewise be
// caught client-side instead of shipping "".
//
// Mock convention (established in signal-quality-card.test.tsx): @/lib/utils
// is a dual-purpose module (API client + shadcn cn()) — an integral module
// mock starves Card/Select/Button of cn before the first assertion, so we
// partially mock: spread the actual module and override only the API
// methods this form calls.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// vi.mock factories are hoisted above every const — the shared spy must be
// created hoisted too or the factory reads it before initialization.
const runBacktest = vi.hoisted(() => vi.fn())

vi.mock('@/lib/utils', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/utils')>()
  return {
    ...actual,
    API: {
      ...actual.API,
      getStrategies: vi.fn().mockResolvedValue({ strategies: [] }),
      runBacktest,
    },
  }
})

import { BacktestForm } from './BacktestForm'

describe('BacktestForm input validation (iterations 136-137)', () => {
  it('blocks submit when initial cash is cleared — field-named error, no API call', async () => {
    render(<BacktestForm />)

    const cash = await screen.findByLabelText(/Initial Cash/i)
    fireEvent.change(cash, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: /Run Backtest/i }))

    expect(await screen.findByText(/初始资金 无效/)).toBeInTheDocument()
    expect(runBacktest).not.toHaveBeenCalled()
  })

  it('blocks submit when the symbol is cleared — named error, no API call', async () => {
    render(<BacktestForm />)

    const symbol = await screen.findByLabelText(/Stock Symbol/i)
    fireEvent.change(symbol, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: /Run Backtest/i }))

    expect(await screen.findByText(/股票代码 不能为空/)).toBeInTheDocument()
    expect(runBacktest).not.toHaveBeenCalled()
  })
})

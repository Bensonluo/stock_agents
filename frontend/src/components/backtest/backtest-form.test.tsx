// @vitest-environment jsdom
// Component-level lock for the input-validation wiring (iterations 136-139):
// a cleared numeric field must block submit with the form's field-named
// Chinese error instead of sending NaN (rendered as null on the wire and
// answered by pydantic's English 422); a cleared symbol must likewise be
// caught client-side instead of shipping ""; a cleared date field must be
// caught before the empty string reaches the wire (iteration 139).
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

    const cash = await screen.findByLabelText(/初始资金/)
    fireEvent.change(cash, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: /开始回测/ }))

    expect(await screen.findByText(/初始资金 无效/)).toBeInTheDocument()
    expect(runBacktest).not.toHaveBeenCalled()
  })

  it('blocks submit when the symbol is cleared — named error, no API call', async () => {
    render(<BacktestForm />)

    const symbol = await screen.findByLabelText(/股票代码/)
    fireEvent.change(symbol, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: /开始回测/ }))

    expect(await screen.findByText(/股票代码 不能为空/)).toBeInTheDocument()
    expect(runBacktest).not.toHaveBeenCalled()
  })

  it('blocks submit when a date is cleared — named error, no API call', async () => {
    render(<BacktestForm />)

    const start = await screen.findByLabelText(/开始日期/)
    fireEvent.change(start, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: /开始回测/ }))

    expect(await screen.findByText(/开始日期 无效/)).toBeInTheDocument()
    expect(runBacktest).not.toHaveBeenCalled()
  })

  it('blocks submit when the range is reversed — cross-field error, no API call', async () => {
    render(<BacktestForm />)

    // Defaults are start 2023-01-01 / end 2024-01-01; moving start past end
    // mirrors the backend's end <= start rejection before the wire.
    const start = await screen.findByLabelText(/开始日期/)
    fireEvent.change(start, { target: { value: '2024-06-15' } })
    fireEvent.click(screen.getByRole('button', { name: /开始回测/ }))

    expect(await screen.findByText(/日期区间无效——结束日期必须晚于开始日期/)).toBeInTheDocument()
    expect(runBacktest).not.toHaveBeenCalled()
  })

  it('blocks submit when sma_short >= sma_long — strategy constraint, no API call', async () => {
    render(<BacktestForm />)

    // Default strategy is sma_crossover (short 20 / long 50); flipping the
    // short period past the long one mirrors the backend's sma_short >=
    // sma_long rejection before the wire.
    const short = await screen.findByLabelText(/短周期/)
    fireEvent.change(short, { target: { value: '50' } })
    fireEvent.click(screen.getByRole('button', { name: /开始回测/ }))

    expect(await screen.findByText(/参数 sma_short 必须小于 sma_long/)).toBeInTheDocument()
    expect(runBacktest).not.toHaveBeenCalled()
  })
})

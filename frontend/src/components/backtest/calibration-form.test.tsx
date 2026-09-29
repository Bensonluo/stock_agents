// @vitest-environment jsdom
// Component-level lock for the calibration form's submit guards, mirroring
// backtest-form.test.tsx (iterations 136-139): a cleared symbol must be
// caught client-side as 股票代码 不能为空 instead of shipping "" (answered by
// pydantic's English 422), and a reversed date range must surface the
// cross-field 日期区间无效 error before the wire. The API spy pins that no
// request leaves the form in either case.
//
// Mock convention (established in signal-quality-card.test.tsx): @/lib/utils
// is a dual-purpose module (API client + shadcn cn()) — an integral module
// mock starves Card/Select/Button of cn before the first assertion, so we
// partially mock: spread the actual module and override only the API
// methods this form calls (getStrategies feeds the mount useEffect and keeps
// the Strategy Select empty; calibrateSignals is the submit target).
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// vi.mock factories are hoisted above every const — the shared spy must be
// created hoisted too or the factory reads it before initialization.
const calibrateSignals = vi.hoisted(() => vi.fn())

vi.mock('@/lib/utils', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/utils')>()
  return {
    ...actual,
    API: {
      ...actual.API,
      getStrategies: vi.fn().mockResolvedValue({ strategies: [] }),
      calibrateSignals,
    },
  }
})

import { CalibrationForm } from './CalibrationForm'

describe('CalibrationForm input validation', () => {
  it('blocks submit when the symbol is cleared — named error, no API call', async () => {
    render(<CalibrationForm />)

    const symbol = await screen.findByLabelText(/股票代码/)
    fireEvent.change(symbol, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: /开始校准/ }))

    expect(await screen.findByText(/股票代码 不能为空/)).toBeInTheDocument()
    expect(calibrateSignals).not.toHaveBeenCalled()
  })

  it('blocks submit when the range is reversed — cross-field error, no API call', async () => {
    render(<CalibrationForm />)

    // Defaults are start 2021-01-01 / end 2024-01-01; moving start past end
    // mirrors the backend's end <= start rejection before the wire.
    const start = await screen.findByLabelText(/开始日期/)
    fireEvent.change(start, { target: { value: '2024-06-15' } })
    fireEvent.click(screen.getByRole('button', { name: /开始校准/ }))

    expect(await screen.findByText(/日期区间无效——结束日期必须晚于开始日期/)).toBeInTheDocument()
    expect(calibrateSignals).not.toHaveBeenCalled()
  })
})

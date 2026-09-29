// @vitest-environment jsdom
// Component-level lock for the root route error boundary (iteration 143).
//
// Before this, every route segment shipped only a page.tsx — no error.tsx
// anywhere — so any render or runtime crash in the page trees fell through
// to Next.js's default English crash screen. The boundary must render a
// Chinese graceful-fallback card that always carries something reportable
// (the Next digest when present, the error message otherwise), a retry
// button wired to reset(), and a way back home.
//
// Mock notes:
// - next/link needs the Next router context under jsdom; the boundary only
//   uses it as a plain anchor, so stub it with one.
// - No @/lib/utils partial mock needed: the boundary calls no API methods,
//   so the dual-purpose module loads its real cn().
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}))

import RouteError from './error'

function makeError(digest?: string): Error & { digest?: string } {
  const error = new Error('Cannot read properties of undefined (reading map)') as Error & {
    digest?: string
  }
  if (digest) error.digest = digest
  return error
}

describe('root route error boundary (error.tsx)', () => {
  it('renders the crash card with the digest as the reportable identity; retry calls reset', async () => {
    const reset = vi.fn()
    render(<RouteError error={makeError('a1b2c3d4')} reset={reset} />)

    expect(await screen.findByText('页面出错了')).toBeInTheDocument()
    expect(screen.getByText('a1b2c3d4')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /重试/ }))
    expect(reset).toHaveBeenCalledTimes(1)
  })

  it('shows the error message when Next provided no digest — never an empty identity', async () => {
    render(<RouteError error={makeError()} reset={vi.fn()} />)

    expect(
      await screen.findByText('Cannot read properties of undefined (reading map)'),
    ).toBeInTheDocument()
  })

  it('offers a link back to the home page', async () => {
    render(<RouteError error={makeError('deadbeef')} reset={vi.fn()} />)

    const home = await screen.findByRole('link', { name: /返回首页/ })
    expect(home).toHaveAttribute('href', '/')
  })
})

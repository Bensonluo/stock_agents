// Shared test setup, run for every test file. The window-guarded block keeps
// node-environment tests (the pure-TS logic pins) untouched — only jsdom
// files get the browser-API stubs Radix / floating-ui need.

// jest-dom matchers (toBeInTheDocument & friends) extend vitest's expect.
// RTL v16 doesn't bundle @testing-library/dom — it is a separate install.
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// RTL's auto-cleanup only registers when a global afterEach exists; with
// vitest globals:false we wire it ourselves, or DOM leaks between tests.
afterEach(cleanup)

if (typeof window !== 'undefined') {
  // jsdom ships neither matchMedia nor ResizeObserver; next-themes and
  // floating-ui (Radix popovers/selects) call both at mount.
  if (!window.matchMedia) {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }),
    })
  }
  if (!globalThis.ResizeObserver) {
    class MockResizeObserver {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    }
    globalThis.ResizeObserver = MockResizeObserver as unknown as typeof ResizeObserver
  }

  // Radix Select opens on pointer events, which jsdom does not implement
  // (no PointerEvent constructor, no capture API, no scrollIntoView).
  // Maintainer-endorsed stubs: radix-ui/primitives#1382.
  const proto = window.HTMLElement.prototype
  if (typeof proto.scrollIntoView !== 'function') proto.scrollIntoView = () => {}
  if (typeof proto.hasPointerCapture !== 'function') proto.hasPointerCapture = () => false
  if (typeof proto.setPointerCapture !== 'function') proto.setPointerCapture = () => {}
  if (typeof proto.releasePointerCapture !== 'function') proto.releasePointerCapture = () => {}
  if (!window.PointerEvent) {
    class MockPointerEvent extends Event {
      button: number
      ctrlKey: boolean
      pointerType: string
      constructor(type: string, props: PointerEventInit = {}) {
        super(type, props)
        this.button = props.button ?? 0
        this.ctrlKey = props.ctrlKey ?? false
        this.pointerType = props.pointerType ?? 'mouse'
      }
    }
    window.PointerEvent = MockPointerEvent as unknown as typeof window.PointerEvent
  }
}

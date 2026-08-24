import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { installKeyboardRouter, type ShortcutHandlers } from '../lib/keyboard'

// We need to simulate the platform (Mac vs non-Mac). The router reads
// navigator.platform at call time so we patch Object.defineProperty on
// navigator. On jsdom default is "" (empty), treated as non-Mac.

function fireKey(key: string, modifiers: { meta?: boolean; ctrl?: boolean; shift?: boolean } = {}, target: EventTarget = window): void {
  const ev = new KeyboardEvent('keydown', {
    key,
    metaKey: modifiers.meta ?? false,
    ctrlKey: modifiers.ctrl ?? false,
    shiftKey: modifiers.shift ?? false,
    bubbles: true,
    cancelable: true,
  })
  target.dispatchEvent(ev)
}

function setPlatform(mac: boolean): void {
  Object.defineProperty(navigator, 'platform', { value: mac ? 'MacIntel' : 'Win32', configurable: true })
}

describe('installKeyboardRouter', () => {
  let handlers: { [K in keyof ShortcutHandlers]: ReturnType<typeof vi.fn> }

  beforeEach(() => {
    handlers = { submit: vi.fn(), stop: vi.fn(), palette: vi.fn(), help: vi.fn() }
    setPlatform(true) // macOS for these tests
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('dispatches submit on Cmd+Enter', () => {
    const cleanup = installKeyboardRouter(handlers)
    fireKey('Enter', { meta: true })
    expect(handlers.submit).toHaveBeenCalledTimes(1)
    cleanup()
  })

  it('dispatches stop on Cmd+.', () => {
    const cleanup = installKeyboardRouter(handlers)
    fireKey('.', { meta: true })
    expect(handlers.stop).toHaveBeenCalledTimes(1)
    cleanup()
  })

  it('dispatches palette on Cmd+K', () => {
    const cleanup = installKeyboardRouter(handlers)
    fireKey('k', { meta: true })
    expect(handlers.palette).toHaveBeenCalledTimes(1)
    cleanup()
  })

  it('dispatches help on Cmd+/', () => {
    const cleanup = installKeyboardRouter(handlers)
    fireKey('/', { meta: true })
    expect(handlers.help).toHaveBeenCalledTimes(1)
    cleanup()
  })

  it('does NOT dispatch when Cmd is not pressed', () => {
    const cleanup = installKeyboardRouter(handlers)
    fireKey('Enter')
    fireKey('k')
    expect(handlers.submit).not.toHaveBeenCalled()
    expect(handlers.palette).not.toHaveBeenCalled()
    cleanup()
  })

  it('ignores non-submit shortcuts when focus is in input', () => {
    const cleanup = installKeyboardRouter(handlers)
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    fireKey('k', { meta: true })
    expect(handlers.palette).not.toHaveBeenCalled()
    document.body.removeChild(input)
    cleanup()
  })

  it('still dispatches submit on Cmd+Enter from inside an input', () => {
    const cleanup = installKeyboardRouter(handlers)
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    fireKey('Enter', { meta: true })
    expect(handlers.submit).toHaveBeenCalledTimes(1)
    document.body.removeChild(input)
    cleanup()
  })

  it('uses Ctrl on non-Mac platforms', () => {
    setPlatform(false)
    const cleanup = installKeyboardRouter(handlers)
    fireKey('Enter', { ctrl: true })
    expect(handlers.submit).toHaveBeenCalledTimes(1)
    // Meta alone should NOT trigger on non-Mac
    handlers.submit.mockClear()
    fireKey('Enter', { meta: true })
    expect(handlers.submit).not.toHaveBeenCalled()
    cleanup()
  })

  it('cleanup removes the listener', () => {
    const cleanup = installKeyboardRouter(handlers)
    cleanup()
    fireKey('Enter', { meta: true })
    expect(handlers.submit).not.toHaveBeenCalled()
  })
})
// useMediaQuery — React hook for matchMedia-driven breakpoints (M15, decision 0019).
//
// Returns true when the given media query currently matches. The hook
// subscribes to `change` events so the value updates live when the
// browser is resized, zoomed, or the OS-level display scaling
// changes (e.g. Windows 11 at 125% / 150% scaling).
//
// Why JS-driven instead of a CSS @media rule? Two reasons:
//
//  1. Windows display-scaling does not always trigger a CSS media
//     re-evaluation. A user on a 1280px-wide laptop at 125% scaling
//     reported that the M12.5 inspector breakpoint would flash to
//     the wrong layout during a zoom-in interaction. Driving the
//     breakpoint from matchMedia via useSyncExternalStore-equivalent
//     logic gives us programmatic access to the value AND keeps the
//     update loop in React's commit phase.
//
//  2. Other parts of the SPA can read `isMobile` (the return value)
//     to make layout decisions without re-deriving the breakpoint
//     themselves.
//
// SSR + jsdom safety:
//   - `typeof window === 'undefined'` covers SSR.
//   - `typeof window.matchMedia !== 'function'` covers jsdom (which
//     does not implement matchMedia by default).
//
// In both cases we default to `false` (desktop layout), matching the
// post-mount behaviour when matchMedia is genuinely absent.
//
// Lazy useState initializer reads mql.matches synchronously before
// first paint, so no flash.

import { useEffect, useState } from 'react'

export function useMediaQuery(query: string): boolean {
  // Lazy initializer — runs once on mount, before first paint.
  // Returns false when matchMedia is unavailable (SSR, jsdom).
  const [matches, setMatches] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false
    if (typeof window.matchMedia !== 'function') return false
    return window.matchMedia(query).matches
  })

  useEffect(() => {
    if (typeof window === 'undefined') return
    if (typeof window.matchMedia !== 'function') return

    const mql = window.matchMedia(query)
    // The change handler fires outside React's effect body (it's a
    // DOM event), so calling setMatches here does NOT trigger the
    // `set-state-in-effect` oxlint warning.
    const onChange = (e: MediaQueryListEvent) => {
      setMatches(e.matches)
    }

    // Some older Safari versions used `addListener` / `removeListener`
    // (MediaQueryList.addListener); the modern spec is `addEventListener`.
    // `addEventListener` is supported in all current evergreen
    // browsers (Chrome 39+, Firefox 6+, Safari 14+).
    if (typeof mql.addEventListener === 'function') {
      mql.addEventListener('change', onChange)
      return () => mql.removeEventListener('change', onChange)
    }
    // Legacy fallback (Safari < 14).
    ;(mql as unknown as {
      addListener: (cb: (e: MediaQueryListEvent) => void) => void
      removeListener: (cb: (e: MediaQueryListEvent) => void) => void
    }).addListener(onChange)
    return () => {
      ;(mql as unknown as {
        removeListener: (cb: (e: MediaQueryListEvent) => void) => void
      }).removeListener(onChange)
    }
  }, [query])

  return matches
}

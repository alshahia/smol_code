// Browser-local last-selection store (M12).
// Persists the last-used (providerId, model) pair across reloads so the SPA
// rehydrates the provider dropdown without forcing the user to re-pick.
// Mirrors keysStore.ts patterns: versioned storage key, silent failure on
// quota/parse errors, SSR-safe (no-op when window/localStorage is absent).
//
// Contract (decision 0015, M12.2):
//   - Stored shape: { providerId: string, model: string }
//   - Empty / missing model is normalised to "" (caller decides fallback).
//   - No PII; no API keys; no env names. Just two short strings.

const STORAGE_KEY = 'smolcode.last.v1'

export interface LastSelection {
  readonly providerId: string
  readonly model: string
}

function isBrowser(): boolean {
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined'
}

function readRaw(): unknown {
  if (!isBrowser()) return null
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (raw === null) return null
    return JSON.parse(raw)
  } catch {
    return null
  }
}

function isLastSelection(x: unknown): x is LastSelection {
  if (x === null || typeof x !== 'object' || Array.isArray(x)) return false
  const o = x as Record<string, unknown>
  return typeof o.providerId === 'string' && typeof o.model === 'string'
}

export function loadLast(): LastSelection | null {
  const raw = readRaw()
  if (!isLastSelection(raw)) return null
  if (raw.providerId.length === 0) return null
  return { providerId: raw.providerId, model: raw.model }
}

export function saveLast(providerId: string, model: string): void {
  if (!isBrowser()) return
  if (typeof providerId !== 'string' || providerId.length === 0) return
  const safeModel = typeof model === 'string' ? model : ''
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ providerId, model: safeModel }))
  } catch {
    /* quota exceeded or storage disabled — silently ignore */
  }
}

export function clearLast(): void {
  if (!isBrowser()) return
  try {
    window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* ignore */
  }
}

export const LAST_SELECTION_LIMITS = {
  storageKey: STORAGE_KEY,
} as const

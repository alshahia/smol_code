// Browser-local API-key store (M11).
// Stores per-provider API keys in localStorage under a single versioned key.
// The values never leave the browser except inside an immediate POST body to
// /api/runs on the same loopback origin. See decision 0014.

const STORAGE_KEY = "smolcode.keys.v1"
const MAX_ENTRIES = 16
const MAX_VALUE_BYTES = 4096

function isBrowser(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined"
}

function readAll(): Record<string, string> {
  if (!isBrowser()) return {}
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {}
    }
    const out: Record<string, string> = {}
    for (const [k, v] of Object.entries(parsed)) {
      if (typeof v === "string" && v.length > 0) {
        out[k] = v
      }
    }
    return out
  } catch {
    return {}
  }
}

function writeAll(map: Record<string, string>): void {
  if (!isBrowser()) return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(map))
  } catch {
    /* quota exceeded or storage disabled — silently ignore */
  }
}

function normalize(value: string): string | null {
  const trimmed = value.replace(/\r/g, "").split("\n", 1)[0].trim()
  if (trimmed.length === 0) return null
  if (trimmed.length > MAX_VALUE_BYTES) return trimmed.slice(0, MAX_VALUE_BYTES)
  return trimmed
}

export interface KeysMap {
  readonly [providerId: string]: string
}

export function loadKeys(): KeysMap {
  return readAll()
}

export function getKey(providerId: string): string | null {
  const all = readAll()
  return Object.hasOwn(all, providerId) ? all[providerId] : null
}

export function saveKey(providerId: string, value: string): boolean {
  const normalized = normalize(value)
  const all = readAll()
  if (normalized === null) {
    delete all[providerId]
    writeAll(all)
    return false
  }
  if (Object.keys(all).length >= MAX_ENTRIES && !Object.hasOwn(all, providerId)) {
    return false
  }
  all[providerId] = normalized
  writeAll(all)
  return true
}

export function deleteKey(providerId: string): void {
  const all = readAll()
  if (Object.hasOwn(all, providerId)) {
    delete all[providerId]
    writeAll(all)
  }
}

export function clearAllKeys(): void {
  if (!isBrowser()) return
  try {
    window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* ignore */
  }
}

export const KEYS_STORE_LIMITS = {
  storageKey: STORAGE_KEY,
  maxEntries: MAX_ENTRIES,
  maxValueBytes: MAX_VALUE_BYTES,
} as const

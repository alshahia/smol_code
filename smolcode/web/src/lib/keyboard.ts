// Phase 3 (decision 0025 sec 6.5 / FE-4): global keyboard shortcut router.
// Installs a window keydown listener that dispatches to the registered
// handlers. Mac uses Cmd; non-Mac uses Ctrl. The router is no-op when
// the focus is in an <input> / <textarea> (except for Enter, which
// still triggers submit on Cmd+Enter / Ctrl+Enter).

export type Shortcut = 'submit' | 'stop' | 'palette' | 'help'

export interface ShortcutHandlers {
  submit: () => void
  stop: () => void
  palette: () => void
  help: () => void
}

function isMac(): boolean {
  if (typeof navigator === 'undefined') return false
  return navigator.platform.toUpperCase().includes('MAC')
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!target) return false
  const el = target as HTMLElement
  const tag = el.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
  if (el.isContentEditable) return true
  // Also check document.activeElement as a fallback for jsdom + dispatch-from-element scenarios.
  if (typeof document !== 'undefined' && document.activeElement && document.activeElement !== document.body) {
    const active = document.activeElement as HTMLElement
    if (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.tagName === 'SELECT') return true
    if (active.isContentEditable) return true
  }
  return false
}

export function installKeyboardRouter(handlers: ShortcutHandlers): () => void {
  function onKey(e: KeyboardEvent): void {
    const mac = isMac()
    const meta = mac ? e.metaKey : e.ctrlKey
    if (!meta) return
    const editable = isEditableTarget(e.target)
    if (e.key === 'Enter' && !e.shiftKey) {
      // Cmd+Enter / Ctrl+Enter from anywhere submits.
      handlers.submit()
      e.preventDefault()
      return
    }
    if (editable) return
    if (e.key === '.') {
      handlers.stop()
      e.preventDefault()
    } else if (e.key.toLowerCase() === 'k') {
      handlers.palette()
      e.preventDefault()
    } else if (e.key === '/') {
      handlers.help()
      e.preventDefault()
    }
  }
  window.addEventListener('keydown', onKey)
  return () => window.removeEventListener('keydown', onKey)
}
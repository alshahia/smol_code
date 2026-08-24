// ApiKeyPanel: per-provider browser-local API-key entry (M11).
// Visible only when the chosen provider has no env-set key AND no key is
// already stored in localStorage for that provider. The value is held in
// component state until "Save" is pressed; on Save it's persisted via
// keysStore.saveKey and the parent's onKeyChange fires so the next /api/runs
// POST body includes it.
//
// Security notes:
//   - Values are never logged, never sent in URL, never read from headers.
//   - Only the *whitelisted* env-var name is shown to the user.
//   - "Forget" removes the entry from localStorage immediately.
//   - Display is masked by default; a "Show" toggle reveals it temporarily.
import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import type { ProviderInfo } from '../api'
import { deleteKey, getKey, saveKey } from '../lib/keysStore'

/**
 * Window in which a second click on Forget is required to actually delete
 * the stored key. After this elapses the button reverts to the neutral
 * "Forget" label (M12, decision 0015).
 */
const FORGET_CONFIRM_WINDOW_MS = 3000

interface Props {
  provider: ProviderInfo
  /** Currently-known key (from localStorage) so we don't show the panel when one exists. */
  hasStoredKey: boolean
  /** Called after a save/delete so the parent re-reads from the store. */
  onKeyChange: (providerId: string, value: string | null) => void
}

export function ApiKeyPanel({ provider, hasStoredKey, onKeyChange }: Props) {
  const [draft, setDraft] = useState('')
  const [show, setShow] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [savedFlash, setSavedFlash] = useState(false)
  const [confirmForget, setConfirmForget] = useState(false)
  const forgetTimerRef = useRef<number | null>(null)

  // Clear any pending confirm timer on unmount or provider change.
  useEffect(() => {
    return () => {
      if (forgetTimerRef.current !== null) {
        window.clearTimeout(forgetTimerRef.current)
        forgetTimerRef.current = null
      }
    }
  }, [])

  // Reset draft whenever the provider changes (don't carry a draft across).
  useEffect(() => {
    setDraft('')
    setShow(false)
    setError(null)
    setSavedFlash(false)
    setConfirmForget(false)
    if (forgetTimerRef.current !== null) {
      window.clearTimeout(forgetTimerRef.current)
      forgetTimerRef.current = null
    }
  }, [provider.id])

  const cancelForgetConfirm = () => {
    setConfirmForget(false)
    if (forgetTimerRef.current !== null) {
      window.clearTimeout(forgetTimerRef.current)
      forgetTimerRef.current = null
    }
  }

  const handleForgetClick = () => {
    if (!confirmForget) {
      setConfirmForget(true)
      forgetTimerRef.current = window.setTimeout(() => {
        setConfirmForget(false)
        forgetTimerRef.current = null
      }, FORGET_CONFIRM_WINDOW_MS)
      return
    }
    // Second click within the window -> actually delete.
    deleteKey(provider.id)
    onKeyChange(provider.id, null)
    cancelForgetConfirm()
  }

  if (provider.key_state === 'set') {
    // Server already has an env-set key. No need to enter anything.
    return (
      <div className="api-key-panel api-key-panel-ok muted small">
        ✓ {provider.env_vars[0] ?? 'API key'} is set on the server (env). Nothing to enter.
      </div>
    )
  }

  if (hasStoredKey) {
    const envName = provider.env_vars[0] ?? 'API key'
    return (
      <div className="api-key-panel api-key-panel-stored">
        <span className="small muted">
          🔑 Browser has a stored {envName}. It will be sent with the next run.
        </span>
        <button
          type="button"
          className={'btn btn-sm ' + (confirmForget ? 'btn-danger' : 'btn-secondary')}
          onClick={handleForgetClick}
          onBlur={cancelForgetConfirm}
          title={
            confirmForget
              ? 'Click again to confirm removing this key from the browser'
              : 'Remove the stored key from this browser'
          }
          aria-live="polite"
        >
          {confirmForget ? 'Confirm forget' : 'Forget'}
        </button>
      </div>
    )
  }

  const handleSave = () => {
    setError(null)
    const trimmed = draft.trim()
    if (trimmed.length === 0) {
      setError('Key cannot be empty.')
      return
    }
    const ok = saveKey(provider.id, draft)
    if (!ok) {
      setError('Storage failed (limit reached or storage disabled).')
      return
    }
    const stored = getKey(provider.id)
    setDraft('')
    setShow(false)
    setSavedFlash(true)
    if (stored !== null) onKeyChange(provider.id, stored)
    window.setTimeout(() => setSavedFlash(false), 2000)
  }

  const envName = provider.env_vars[0] ?? 'API key'
  return (
    <div className="api-key-panel api-key-panel-enter">
      <label className="small muted" htmlFor={'api-key-' + provider.id}>
        Enter <code>{envName}</code> for <strong>{provider.name}</strong>
      </label>
      <div className="api-key-row">
        <input
          id={'api-key-' + provider.id}
          type={show ? 'text' : 'password'}
          className="api-key-input"
          value={draft}
          onChange={(e: ChangeEvent<HTMLInputElement>) => setDraft(e.target.value)}
          placeholder={'Paste your ' + envName + ' here'}
          autoComplete="off"
          spellCheck={false}
        />
        <button
          type="button"
          className="btn btn-sm btn-secondary"
          onClick={() => setShow((s) => !s)}
          title={show ? 'Hide the value' : 'Show the value'}
        >
          {show ? 'Hide' : 'Show'}
        </button>
        <button
          type="button"
          className="btn btn-sm btn-primary"
          onClick={handleSave}
          disabled={draft.trim().length === 0}
        >
          Save
        </button>
      </div>
      <div className="small muted api-key-note">
        Stored in this browser only (browser-local). Cleared on Forget.
      </div>
      {error && <div className="error-banner">{error}</div>}
      {savedFlash && (
        <div className="api-key-saved small">✓ Saved. It will be sent on the next run.</div>
      )}
    </div>
  )
}

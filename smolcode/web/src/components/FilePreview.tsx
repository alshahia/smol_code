// FilePreview: tabbed viewer for a single file (Phase 2 A4).
//
// Renders the result of ``GET /api/files?path=...&project=...`` in a
// <pre> block. Syntax highlighting is deliberately omitted (smolcode's
// file viewer is a convenience, not an IDE -- decision 0025 §2.4).

import { useEffect, useState } from 'react'
import { readFile, type FileReadResponse } from '../api'

interface Props {
  /** Absolute or project-relative path; null closes the preview. */
  path: string | null
  /** Project name for the active project; null = legacy workspace. */
  project: string | null
  /** Called when the user clicks the close (x) button. */
  onClose?: () => void
  /** Max bytes to request (default 256 KB matches the server default). */
  maxBytes?: number
}

export function FilePreview({ path, project, onClose, maxBytes = 256 * 1024 }: Props) {
  const [data, setData] = useState<FileReadResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (!path) {
      setData(null)
      setErr(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setErr(null)
    readFile({ path, project, maxBytes })
      .then((res) => {
        if (cancelled) return
        setData(res)
      })
      .catch((e) => {
        if (cancelled) return
        setErr((e as Error).message)
        setData(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [path, project, maxBytes])

  if (!path) return null

  return (
    <div className="file-preview" role="dialog" aria-label={`File preview: ${path}`}>
      <header className="file-preview-header">
        <span className="file-preview-path" title={data?.abs_path ?? path}>
          {path}
        </span>
        {data && (
          <span className="muted small file-preview-meta">
            {data.size.toLocaleString()} bytes{' '}
            {data.encoding === 'binary' ? '(binary)' : ''}
            {data.truncated ? ' — truncated' : ''}
          </span>
        )}
        {onClose && (
          <button
            type="button"
            className="btn btn-secondary file-preview-close"
            onClick={onClose}
            aria-label="Close preview"
          >
            ×
          </button>
        )}
      </header>
      <div className="file-preview-body">
        {loading && <div className="muted small">Loading…</div>}
        {err && <div className="error-banner">{err}</div>}
        {data && (
          <pre className="file-preview-content">
            <code>{data.content}</code>
          </pre>
        )}
      </div>
    </div>
  )
}

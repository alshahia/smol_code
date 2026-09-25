// Upload drop zone + file picker. Calls POST /api/uploads on drop.
// Shows preview chips with size + mime + delete button per file.
import { useState, useRef, useCallback, type DragEvent, type ChangeEvent, type FC } from 'react'
import { uploadFile, type UploadMetadata } from '../api'

interface Props {
  tier: string
  onUploaded: (m: UploadMetadata) => void
  /** Server-configured cap (bytes) from GET /api/config. */
  maxBytes?: number
}

// Plan 6.4 #2 (R14). The hint used to read "up to 50 MB each" as a literal,
// which is wrong the moment SMOLCODE_UPLOAD_MAX_BYTES is set to anything
// else. A stated limit that disagrees with the enforced one is worse than no
// limit: the user trusts it.
const DEFAULT_MAX_BYTES = 50 * 1024 * 1024

function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return ""
  const mb = n / (1024 * 1024)
  if (mb >= 1) return `${Math.round(mb * 10) / 10} MB`
  return `${Math.round(n / 1024)} KB`
}

export const UploadDropZone: FC<Props> = ({ tier, onUploaded, maxBytes = DEFAULT_MAX_BYTES }) => {
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const limitLabel = formatBytes(maxBytes)

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      setError(null)
      setBusy(true)
      try {
        for (const file of Array.from(files)) {
          try {
            // Same number the server enforces, checked before the upload so
            // an oversized file fails immediately instead of after a full
            // round trip. The server still enforces it; this is courtesy.
            if (file.size > maxBytes) {
              throw new Error("file is " + formatBytes(file.size) + ", limit is " + formatBytes(maxBytes))
            }
            const meta = await uploadFile(file, tier)
            onUploaded(meta)
          } catch (e) {
            setError(`${file.name}: ${(e as Error).message}`)
          }
        }
      } finally {
        setBusy(false)
      }
    },
    [tier, onUploaded, maxBytes],
  )

  const onDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault()
      setDragging(false)
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        void handleFiles(e.dataTransfer.files)
      }
    },
    [handleFiles],
  )

  const onDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragging(true)
  }, [])

  const onDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragging(false)
  }, [])

  const onPick = useCallback((e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      void handleFiles(e.target.files)
      e.target.value = ''
    }
  }, [handleFiles])

  return (
    <div
      className={'dropzone' + (dragging ? ' dropzone-dragging' : '')}
      onDrop={onDrop}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onClick={() => inputRef.current?.click()}
      role="button"
      tabIndex={0}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        style={{ display: 'none' }}
        onChange={onPick}
      />
      <div className="dropzone-icon">{'📎'}</div>
      <div className="dropzone-text">
        {busy
          ? 'Uploading…'
          : dragging
            ? 'Drop to upload'
            : 'Drop files here, or click to browse'}
      </div>
      <div className="dropzone-hint">
        PDF, CSV, images, code, text{limitLabel ? " — up to " + limitLabel + " each" : ""}
      </div>
      {error && <div className="dropzone-error">{error}</div>}
    </div>
  )
}

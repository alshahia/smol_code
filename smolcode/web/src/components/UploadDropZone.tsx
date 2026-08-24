// Upload drop zone + file picker. Calls POST /api/uploads on drop.
// Shows preview chips with size + mime + delete button per file.
import { useState, useRef, useCallback, type DragEvent, type ChangeEvent, type FC } from 'react'
import { uploadFile, type UploadMetadata } from '../api'

interface Props {
  tier: string
  onUploaded: (m: UploadMetadata) => void
}

export const UploadDropZone: FC<Props> = ({ tier, onUploaded }) => {
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      setError(null)
      setBusy(true)
      try {
        for (const file of Array.from(files)) {
          try {
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
    [tier, onUploaded],
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
      <div className="dropzone-hint">PDF, CSV, images, code, text — up to 50 MB each</div>
      {error && <div className="dropzone-error">{error}</div>}
    </div>
  )
}

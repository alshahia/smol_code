// Upload list: shows uploaded files with size/mime/sha and a delete button.
import { type FC } from 'react'
import { deleteUpload, type UploadMetadata } from '../api'

interface Props {
  uploads: UploadMetadata[]
  onDeleted: (name: string) => void
}

function fmtSize(b: number): string {
  if (b < 1024) return b + ' B'
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB'
  return (b / 1024 / 1024).toFixed(2) + ' MB'
}

export const UploadList: FC<Props> = ({ uploads, onDeleted }) => {
  if (uploads.length === 0) {
    return <div className="empty">(no uploads yet)</div>
  }
  return (
    <ul className="upload-list">
      {uploads.map((u) => (
        <li key={u.stored_name} className="upload-row">
          <div className="upload-meta">
            <div className="upload-name" title={u.original_name}>
              {u.original_name}
            </div>
            <div className="upload-sub">
              {fmtSize(u.size)} · {u.mime} · {u.tier}
            </div>
            <div className="upload-sha">{u.sha256.slice(0, 12)}…</div>
          </div>
          <button
            className="upload-delete"
            onClick={() => {
              void deleteUpload(u.stored_name).then(() => onDeleted(u.stored_name))
            }}
            title={`Delete ${u.stored_name}`}
          >
            ×
          </button>
        </li>
      ))}
    </ul>
  )
}
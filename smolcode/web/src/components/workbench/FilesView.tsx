// Files: the actual workspace tree, plus the footprint of this run.
// Clicking a file opens the existing read-only FilePreview drawer.

import { WorkspaceTree } from '../WorkspaceTree'
import { Icon } from './Icon'

interface FilesViewProps {
  workspaceRoot: string
  project: string | null
  touchedPaths: string[]
  refreshTrigger: number
  onFileClick: (path: string) => void
  onOpenPath: (path: string) => void
}

export function FilesView({
  workspaceRoot,
  project,
  touchedPaths,
  refreshTrigger,
  onFileClick,
  onOpenPath,
}: FilesViewProps) {
  return (
    <div className="files-wrap">
      <div className="files-head">
        <div>
          <h2>Workspace</h2>
          <p>
            {project ? project + ' · ' : ''}
            {workspaceRoot}
          </p>
        </div>
        <button type="button" className="btn" onClick={() => onOpenPath(workspaceRoot)}>
          <Icon name="folder" size={13} /> Open workspace
        </button>
      </div>
      <div className="files-grid wb-files-grid">
        <div>
          <WorkspaceTree
            workspaceRoot={workspaceRoot}
            touchedPaths={touchedPaths}
            refreshTrigger={refreshTrigger}
            project={project}
            onFileClick={onFileClick}
          />
        </div>
        <div className="files-side">
          <div className="files-side-card">
            <h3>Run footprint</h3>
            {touchedPaths.length === 0 ? (
              <p className="muted">
                This run has not written a file. The tree highlights any path it touches.
              </p>
            ) : (
              <div className="touched-list">
                {touchedPaths.map((path) => (
                  <button key={path} type="button" onClick={() => onFileClick(path)}>
                    {path}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="files-side-card">
            <h3>Read-only preview</h3>
            <p className="muted">
              Files open in a drawer over the stage. The preview never writes to the workspace.
            </p>
          </div>
          <div className="files-side-card">
            <h3>Sandbox boundary</h3>
            <p className="muted">
              The workspace tree is scoped to the selected project. Writes outside it require an
              explicit release at the gate.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

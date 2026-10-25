// Context drawer: the facts that used to live in a permanent right pane.
// Opening it is deliberate, so the run keeps the stage.

import type {
  ConfigResponse,
  ProviderInfo,
  RunSummary,
  UploadMetadata,
} from '../../api'
import { ApiKeyPanel } from '../ApiKeyPanel'
import { UploadDropZone } from '../UploadDropZone'
import { UploadList } from '../UploadList'
import { AllowlistSimulator } from '../AllowlistSimulator'
import { SubAgentList } from '../SubAgentList'
import { ProjectSwitcher } from '../ProjectSwitcher'
import { Icon } from './Icon'

interface ContextPanelProps {
  config: ConfigResponse
  activeRun: RunSummary | null
  activeProject: string | null
  activeSessionId: string | null
  projectsRefreshTrigger: number
  providers: ProviderInfo[]
  selectedProviderId: string | null
  selectedProvider: ProviderInfo | null
  selectedModel: string
  storedKeyValue: string | null
  uploads: UploadMetadata[]
  onProjectChange: (project: string | null) => void
  onProviderChange: (providerId: string, model: string) => void
  onModelChange: (model: string) => void
  onKeyChange: (providerId: string, value: string | null) => void
  onUploaded: () => void
  onOpenPath: (path: string) => void
  onOpenRuns: () => void
  onOpenSessions: () => void
}

export function ContextPanel({
  config,
  activeRun,
  activeProject,
  activeSessionId,
  projectsRefreshTrigger,
  providers,
  selectedProviderId,
  selectedProvider,
  selectedModel,
  storedKeyValue,
  uploads,
  onProjectChange,
  onProviderChange,
  onModelChange,
  onKeyChange,
  onUploaded,
  onOpenPath,
  onOpenRuns,
  onOpenSessions,
}: ContextPanelProps) {
  return (
    <div className="context-panel">
      <section className="drawer-section">
        <div className="context-run-head">
          <div className="grow">
            <h3>{activeRun ? activeRun.task : 'No run open'}</h3>
            <p>{activeRun ? activeRun.id + ' · ' + activeRun.status : 'Pick a run from the rail or open Runs.'}</p>
          </div>
          <button type="button" className="btn" onClick={onOpenRuns}>
            Runs
          </button>
        </div>
        {activeRun ? (
          <>
            <div className="kv"><span className="k">Tier</span><span className="v">{activeRun.tier}</span></div>
            <div className="kv"><span className="k">Model</span><span className="v">{activeRun.model || '—'} {activeRun.provider ? '(' + activeRun.provider + ')' : ''}</span></div>
            <div className="kv"><span className="k">Workspace</span><span className="v">{activeRun.effective_cwd || config.workspace}</span></div>
            <div className="kv"><span className="k">Tokens</span><span className="v">{activeRun.tokens ? activeRun.tokens.total.toLocaleString() : '0'}</span></div>
            <div className="kv">
              <span className="k">Cost</span>
              <span className="v">{activeRun.tokens?.cost_usd != null ? '$' + activeRun.tokens.cost_usd.toFixed(4) : 'not rated'}</span>
            </div>
            <div className="kv"><span className="k">Remaining</span><span className="v">{activeRun.remaining_s != null ? activeRun.remaining_s + 's' : '—'}</span></div>
            {activeRun.error ? <p className="error-text small">{activeRun.error}</p> : null}
            <div className="section-actions">
              <button type="button" className="btn" onClick={() => onOpenPath(activeRun.effective_cwd || config.workspace)}>
                <Icon name="folder" size={12} /> Open working root
              </button>
              <button type="button" className="btn" onClick={onOpenSessions}>
                <Icon name="panel" size={12} /> Session {activeSessionId ? activeSessionId.slice(0, 8) : 'none'}
              </button>
            </div>
            <SubAgentList history={activeRun.subagent_history || []} />
          </>
        ) : (
          <p className="help">
            A run is the unit of work. Start one in the composer or choose an earlier run from the rail.
          </p>
        )}
      </section>

      <section className="drawer-section">
        <h3>Project</h3>
        <p className="help">Scopes the workspace tree, uploads and new runs.</p>
        <ProjectSwitcher
          value={activeProject}
          onChange={onProjectChange}
          refreshTrigger={projectsRefreshTrigger}
          workspace={config.workspace}
        />
        {activeProject ? (
          <div className="kv" style={{ marginTop: 8 }}>
            <span className="k">Selected</span>
            <span className="v">{activeProject}</span>
          </div>
        ) : null}
      </section>

      <section className="drawer-section">
        <h3>Model provider</h3>
        <div className="provider-selector">
          <label className="sr-only" htmlFor="context-provider">Provider</label>
          <select
            id="context-provider"
            className="provider-select"
            value={selectedProviderId || ''}
            onChange={(event) => {
              const id = event.target.value
              const info = providers.find((p) => p.id === id)
              onProviderChange(id, info?.default_model || '')
            }}
          >
            {providers.length === 0 ? <option value="">No providers reported</option> : null}
            {providers.map((provider) => (
              <option key={provider.id} value={provider.id}>
                {provider.name}
              </option>
            ))}
          </select>
        </div>
        <div className="model-row">
          <label className="sr-only" htmlFor="context-model">Model</label>
          <input
            id="context-model"
            className="model-input"
            value={selectedModel}
            spellCheck={false}
            placeholder="model-id"
            onChange={(event) => onModelChange(event.target.value)}
          />
        </div>
        {selectedProvider ? (
          <ApiKeyPanel
            provider={selectedProvider}
            hasStoredKey={storedKeyValue !== null}
            onKeyChange={onKeyChange}
          />
        ) : null}
      </section>

      <section className="drawer-section">
        <h3>Uploads</h3>
        <p className="help">Files made available to the run. {uploads.length} in this project.</p>
        <UploadDropZone tier="restricted" maxBytes={config.upload_max_bytes} onUploaded={onUploaded} />
        <UploadList uploads={uploads} onDeleted={onUploaded} />
      </section>

      <section className="drawer-section">
        <h3>Tier policy</h3>
        <p className="help">The ladder is the product. A higher tier is a wider blast radius, not a better mode.</p>
        <div className="policy-list">
          {config.tiers.map((tier) => (
            <div className="policy-item" key={tier.name}>
              <div className="policy-item-head">
                <b>{tier.name}</b>
                <code>{tier.network} network</code>
              </div>
              <p>
                {tier.uploads} uploads · {tier.max_steps} steps · {tier.timeout_s}s timeout · <code>{tier.docker_image}</code>
              </p>
            </div>
          ))}
        </div>
      </section>

      <section className="drawer-section">
        <h3>Allowlist simulator</h3>
        <p className="help">Check a tool call against a tier's policy before a run uses it.</p>
        <AllowlistSimulator tiers={config.tiers.map((tier) => tier.name)} defaultTier="restricted" />
      </section>
    </div>
  )
}

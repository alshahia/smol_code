// Allowlist simulator: pick tool + tier, enter args, see if allowed.
// Useful for debugging "why was my command blocked?" without running an agent.
import { useState, type FC, type FormEvent } from 'react'
import { checkAllowlist, type AllowlistCheckResponse } from '../api'

interface Props {
  tiers: string[]
  defaultTier: string
}

export const AllowlistSimulator: FC<Props> = ({ tiers, defaultTier }) => {
  const [tool, setTool] = useState('shell.run')
  const [tier, setTier] = useState(defaultTier)
  const [cmd, setCmd] = useState('pytest')
  const [path, setPath] = useState('src/foo.py')
  const [result, setResult] = useState<AllowlistCheckResponse | null>(null)
  const [busy, setBusy] = useState(false)

  const onCheck = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setResult(null)
    try {
      const args: Record<string, unknown> = tool === 'shell.run' ? { cmd } : { path }
      const r = await checkAllowlist(tool, args, tier)
      setResult(r)
    } catch (err) {
      setResult({ allowed: false, reason: 'error: ' + (err as Error).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="allowlist-sim" onSubmit={onCheck}>
      <h3>Allowlist simulator</h3>
      <label>
        Tool
        <select value={tool} onChange={(e) => setTool(e.target.value)}>
          <option value="shell.run">shell.run</option>
          <option value="fs.write_file">fs.write_file</option>
        </select>
      </label>
      <label>
        Tier
        <select value={tier} onChange={(e) => setTier(e.target.value)}>
          {tiers.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>
      <label>
        {tool === 'shell.run' ? 'cmd' : 'path'}
        <input
          type="text"
          value={tool === 'shell.run' ? cmd : path}
          onChange={(e) => (tool === 'shell.run' ? setCmd(e.target.value) : setPath(e.target.value))}
        />
      </label>
      <button type="submit" disabled={busy}>
        {busy ? 'checking…' : 'Check'}
      </button>
      {result && (
        <div className={'result ' + (result.allowed ? 'ok' : 'no')}>
          {result.allowed ? '✓' : '✗'} {result.reason}
        </div>
      )}
    </form>
  )
}

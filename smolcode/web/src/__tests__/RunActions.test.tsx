// v1.9.x (FE-7, B4/B5/B7): tests for the RunActions button cluster
// rendered next to a terminal run in the stream header.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return {
    ...actual,
    retryRun: vi.fn(),
    rerunRun: vi.fn(),
    exportRun: vi.fn(),
    downloadExport: vi.fn(),
  }
})

import * as api from '../api'
import { RunActions } from '../components/RunActions'

const mockedApi = vi.mocked(api)

describe('RunActions', () => {
  beforeEach(() => {
    mockedApi.retryRun.mockReset()
    mockedApi.rerunRun.mockReset()
    mockedApi.exportRun.mockReset()
    mockedApi.downloadExport.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders Retry / Re-run / Export buttons', () => {
    render(<RunActions runId="run-1" />)
    expect(screen.getByRole('button', { name: /^retry$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /re-run/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^export$/i })).toBeInTheDocument()
  })

  it('Retry button calls api.retryRun with the runId', async () => {
    const user = userEvent.setup()
    mockedApi.retryRun.mockResolvedValue({ run_id: 'new-run', status: 'pending' })
    render(<RunActions runId="run-1" />)
    await user.click(screen.getByRole('button', { name: /^retry$/i }))
    expect(mockedApi.retryRun).toHaveBeenCalledWith('run-1')
  })

  it('Re-run button calls api.rerunRun with the runId', async () => {
    const user = userEvent.setup()
    mockedApi.rerunRun.mockResolvedValue({ run_id: 'new-run-2', status: 'pending' })
    render(<RunActions runId="run-2" />)
    await user.click(screen.getByRole('button', { name: /re-run/i }))
    expect(mockedApi.rerunRun).toHaveBeenCalledWith('run-2')
  })

  it('Export button calls api.exportRun + api.downloadExport', async () => {
    const user = userEvent.setup()
    const payload = {
      summary: {
        id: 'run-3',
        task: 't',
        tier: 'restricted',
        status: 'done' as const,
        started_at: 1,
        ended_at: 2,
        duration_s: 1,
        result: null,
        error: null,
        has_pending_approval: false,
      },
      events: [],
      subagent_history: [],
      exported_at: 1,
      schema_version: 1,
    }
    mockedApi.exportRun.mockResolvedValue(payload)
    render(<RunActions runId="run-3" />)
    await user.click(screen.getByRole('button', { name: /^export$/i }))
    expect(mockedApi.exportRun).toHaveBeenCalledWith('run-3')
    expect(mockedApi.downloadExport).toHaveBeenCalledWith('run-3', payload)
  })
})

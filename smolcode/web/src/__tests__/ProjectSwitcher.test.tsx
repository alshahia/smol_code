// Phase 4 F4 (decision 0037): basic tests for ProjectSwitcher.
// Verifies the form sends {name, root} when both fields are filled, falls
// back to {name} when the path is empty, and renders Browse + Path input.

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return { ...actual, listProjects: vi.fn(), createProject: vi.fn(), deleteProject: vi.fn() }
})

import * as api from '../api'
import { ProjectSwitcher } from '../components/ProjectSwitcher'

const mockedApi = vi.mocked(api)
const STORAGE_KEY = 'smolcode.recentProjects.v1'

function clearRecents() { if (typeof window !== 'undefined' && typeof window.localStorage !== 'undefined') window.localStorage.removeItem(STORAGE_KEY) }

describe('ProjectSwitcher (Phase 4 basics)', () => {
  beforeEach(() => { clearRecents(); mockedApi.listProjects.mockReset(); mockedApi.createProject.mockReset(); mockedApi.deleteProject.mockReset(); mockedApi.listProjects.mockResolvedValue({ projects: [] }) })
  afterEach(() => { vi.restoreAllMocks() })

  it('renders the workspace selector with the (workspace) default option', async () => {
    render(<ProjectSwitcher value={null} onChange={() => {}} workspace='/ws' />)
    const select = screen.getByLabelText(/Active project/i)
    expect(select).toBeInTheDocument()
    const opts = within(select as HTMLSelectElement).getAllByRole('option')
    expect(opts[0]).toHaveTextContent('(workspace)')
  })

  it('shows both a Name input and a Path input (Phase 4 affordance)', () => {
    render(<ProjectSwitcher value={null} onChange={() => {}} workspace='/ws' />)
    expect(screen.getByLabelText(/New project name/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/New project root path/i)).toBeInTheDocument()
  })

  it('shows a Browse button (and a hidden file input)', () => {
    render(<ProjectSwitcher value={null} onChange={() => {}} workspace='/ws' />)
    expect(screen.getByRole('button', { name: /Browse for project folder/i })).toBeInTheDocument()
    expect(screen.getByTestId('project-browse-input')).toBeInTheDocument()
  })

  it('create with both name + path POSTs {name, root}', async () => {
    const user = userEvent.setup()
    mockedApi.createProject.mockResolvedValue({ name: 'ext', root: '/somewhere/out' })
    const onChange = vi.fn()
    render(<ProjectSwitcher value={null} onChange={onChange} workspace='/ws' />)
    await user.type(screen.getByLabelText(/New project name/i), 'ext')
    await user.type(screen.getByLabelText(/New project root path/i), '/somewhere/out')
    await user.keyboard('{Enter}')
    expect(mockedApi.createProject).toHaveBeenCalledTimes(1)
    expect(mockedApi.createProject).toHaveBeenCalledWith({ name: 'ext', root: '/somewhere/out' })
    expect(onChange).toHaveBeenCalledWith('ext')
  })

  it('create with only a name (no path) keeps the legacy {name} contract', async () => {
    const user = userEvent.setup()
    mockedApi.createProject.mockResolvedValue({ name: 'legacy', root: '/ws/legacy' })
    const onChange = vi.fn()
    render(<ProjectSwitcher value={null} onChange={onChange} workspace='/ws' />)
    await user.type(screen.getByLabelText(/New project name/i), 'legacy')
    await user.keyboard('{Enter}')
    expect(mockedApi.createProject).toHaveBeenCalledWith({ name: 'legacy' })
    expect(onChange).toHaveBeenCalledWith('legacy')
  })

  it('create with empty/whitespace name is a no-op (no API call)', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<ProjectSwitcher value={null} onChange={() => {}} workspace='/ws' />)
    await user.type(screen.getByLabelText(/New project name/i), '   ')
    await user.keyboard('{Enter}')
    expect(mockedApi.createProject).not.toHaveBeenCalled()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('selecting an existing project invokes onChange with the project name', async () => {
    const user = userEvent.setup()
    mockedApi.listProjects.mockResolvedValue({ projects: [{ name: 'one', root: '/ws/one' }, { name: 'two', root: '/ws/two' }] })
    const onChange = vi.fn()
    render(<ProjectSwitcher value={null} onChange={onChange} workspace='/ws' />)
    const select = await screen.findByLabelText(/Active project/i)
    await user.selectOptions(select, 'two')
    expect(onChange).toHaveBeenCalledWith('two')
  })
})

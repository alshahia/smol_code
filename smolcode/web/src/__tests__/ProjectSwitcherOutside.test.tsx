// Phase 4 F4 (decision 0037): tests for the OUTSIDE-WORKSPACE branch + recents.
//   - Outside-workspace notice renders only when the typed path sits outside
//     the live workspace (case-insensitive containment).
//   - Recents list: persist to localStorage, dedupe by name, cap at 8,
//     fill form on click, clear with the xR button.

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return { ...actual, listProjects: vi.fn(), createProject: vi.fn(), deleteProject: vi.fn() }
})

import * as api from '../api'
import {
  ProjectSwitcher,
  isOutsideWorkspace,
  MAX_RECENT_PROJECTS,
  RECENT_PROJECTS_KEY,
  type RecentProject,
} from '../components/ProjectSwitcher'

const mockedApi = vi.mocked(api)

function setRecents(list: RecentProject[]): void { window.localStorage.setItem(RECENT_PROJECTS_KEY, JSON.stringify(list)) }
function clearRecents(): void { window.localStorage.removeItem(RECENT_PROJECTS_KEY) }

describe('isOutsideWorkspace (pure helper)', () => {
  it('returns false for empty target or empty workspace', () => {
    expect(isOutsideWorkspace('', '/ws')).toBe(false)
    expect(isOutsideWorkspace('/anywhere', '')).toBe(false)
    expect(isOutsideWorkspace('/anywhere', undefined)).toBe(false)
    expect(isOutsideWorkspace('/anywhere', null)).toBe(false)
  })
  it('returns false for exact match (case + slash-insensitive)', () => {
    expect(isOutsideWorkspace('/ws', '/ws')).toBe(false)
    expect(isOutsideWorkspace('C:/ws/x', 'c:/ws/x')).toBe(false)
  })
  it('returns false when target is a strict subpath of workspace', () => {
    expect(isOutsideWorkspace('/ws/sub/file.py', '/ws')).toBe(false)
    expect(isOutsideWorkspace('/ws/sub', '/ws')).toBe(false)
  })
  it('returns true when target escapes the workspace by name (different drive)', () => {
    expect(isOutsideWorkspace('D:/outside', 'C:/ws')).toBe(true)
    expect(isOutsideWorkspace('/etc/passwd', '/ws')).toBe(true)
  })
})

describe('ProjectSwitcher (Phase 4 outside-workspace + recents)', () => {
  beforeEach(() => {
    clearRecents()
    mockedApi.listProjects.mockReset()
    mockedApi.createProject.mockReset()
    mockedApi.deleteProject.mockReset()
    mockedApi.listProjects.mockResolvedValue({ projects: [] })
  })
  afterEach(() => { vi.restoreAllMocks(); clearRecents() })

  it('renders no outside-workspace notice when the path input is empty', () => {
    render(<ProjectSwitcher value={null} onChange={() => {}} workspace='/ws' />)
    expect(screen.queryByRole('note')).toBeNull()
  })

  it('renders no outside-workspace notice when the path is inside the workspace', async () => {
    const user = userEvent.setup()
    render(<ProjectSwitcher value={null} onChange={() => {}} workspace='/ws' />)
    await user.type(screen.getByLabelText(/New project root path/i), '/ws/subdir/file.py')
    expect(screen.queryByRole('note')).toBeNull()
  })

  it('renders the outside-workspace notice when the path sits outside the workspace', async () => {
    const user = userEvent.setup()
    render(<ProjectSwitcher value={null} onChange={() => {}} workspace='/ws' />)
    await user.type(screen.getByLabelText(/New project root path/i), '/somewhere/else')
    const note = screen.getByRole('note')
    expect(note).toBeInTheDocument()
    expect(note.textContent).toMatch(/outside the default workspace/i)
    expect(note.textContent).toMatch(/\/ws/)
  })

  it('does not render the outside-workspace notice when no workspace prop is supplied', async () => {
    const user = userEvent.setup()
    render(<ProjectSwitcher value={null} onChange={() => {}} />)
    await user.type(screen.getByLabelText(/New project root path/i), '/somewhere/else')
    expect(screen.queryByRole('note')).toBeNull()
  })

  it('successful create writes a single entry to localStorage recents (FIFO + capped)', async () => {
    const user = userEvent.setup()
    mockedApi.createProject.mockResolvedValue({ name: 'ext', root: '/somewhere/out' })
    render(<ProjectSwitcher value={null} onChange={() => {}} workspace='/ws' />)
    await user.type(screen.getByLabelText(/New project name/i), 'ext')
    await user.type(screen.getByLabelText(/New project root path/i), '/somewhere/out')
    await user.keyboard('{Enter}')
    expect(mockedApi.createProject).toHaveBeenCalledTimes(1)
    const raw = window.localStorage.getItem(RECENT_PROJECTS_KEY)
    const parsed = JSON.parse(raw ?? '[]') as RecentProject[]
    expect(parsed.length).toBe(1)
    expect(parsed[0].name).toBe('ext')
    expect(parsed[0].root).toBe('/somewhere/out')
    expect(typeof parsed[0].last_used).toBe('number')
  })

  it('multiple creates dedupe by name and move the entry to the top', async () => {
    const user = userEvent.setup()
    mockedApi.createProject.mockImplementation(async (req) => ({ name: req.name, root: req.root || '/ws/' + req.name }))
    render(<ProjectSwitcher value={null} onChange={() => {}} workspace='/ws' />)
    await user.type(screen.getByLabelText(/New project name/i), 'a')
    await user.type(screen.getByLabelText(/New project root path/i), '/ws/a')
    await user.keyboard('{Enter}')
    await user.type(screen.getByLabelText(/New project name/i), 'b')
    await user.type(screen.getByLabelText(/New project root path/i), '/ws/b')
    await user.keyboard('{Enter}')
    let parsed = JSON.parse(window.localStorage.getItem(RECENT_PROJECTS_KEY) ?? '[]') as RecentProject[]
    expect(parsed.map((r) => r.name)).toEqual(['b', 'a'])
    await user.type(screen.getByLabelText(/New project name/i), 'a')
    await user.type(screen.getByLabelText(/New project root path/i), '/ws/a-new')
    await user.keyboard('{Enter}')
    parsed = JSON.parse(window.localStorage.getItem(RECENT_PROJECTS_KEY) ?? '[]') as RecentProject[]
    expect(parsed.map((r) => r.name)).toEqual(['a', 'b'])
    expect(parsed[0].root).toBe('/ws/a-new')
  })

  it('cap on recents is MAX_RECENT_PROJECTS (oldest is dropped)', async () => {
    const seed: RecentProject[] = []
    for (let i = 0; i < MAX_RECENT_PROJECTS; i++) seed.push({ name: 'n' + i, root: '/ws/n' + i, last_used: i })
    setRecents(seed)
    mockedApi.createProject.mockResolvedValue({ name: 'new', root: '/ws/new' })
    const user = userEvent.setup()
    render(<ProjectSwitcher value={null} onChange={() => {}} workspace='/ws' />)
    await user.type(screen.getByLabelText(/New project name/i), 'new')
    await user.type(screen.getByLabelText(/New project root path/i), '/ws/new')
    await user.keyboard('{Enter}')
    const parsed = JSON.parse(window.localStorage.getItem(RECENT_PROJECTS_KEY) ?? '[]') as RecentProject[]
    expect(parsed.length).toBe(MAX_RECENT_PROJECTS)
    expect(parsed[0].name).toBe('new')
    expect(parsed.some((r) => r.name === 'n7')).toBe(false)
    expect(parsed.some((r) => r.name === 'n0')).toBe(true)
  })

  it('clicking a recent entry fills the name + path form fields', async () => {
    setRecents([
      { name: 'old', root: '/old/path', last_used: 1 },
      { name: 'newer', root: '/newer/path', last_used: 2 },
    ])
    const user = userEvent.setup()
    render(<ProjectSwitcher value={null} onChange={() => {}} workspace='/ws' />)
    const recent = screen.getByRole('combobox', { name: 'Recent projects' })
    await user.selectOptions(recent, '0') // index 0 = 'old'
    expect((screen.getByLabelText(/New project name/i) as HTMLInputElement).value).toBe('old')
    expect((screen.getByLabelText(/New project root path/i) as HTMLInputElement).value).toBe('/old/path')
  })

  it('xR (clear recents) empties localStorage and the dropdown', async () => {
    setRecents([{ name: 'x', root: '/x', last_used: 1 }])
    const user = userEvent.setup()
    render(<ProjectSwitcher value={null} onChange={() => {}} workspace='/ws' />)
    expect(screen.getByRole('combobox', { name: 'Recent projects' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Clear recent projects/i }))
    expect(window.localStorage.getItem(RECENT_PROJECTS_KEY)).toBe('[]')
    expect(screen.queryByRole('combobox', { name: 'Recent projects' })).toBeNull()
  })

  it('delete also removes the project from recents', async () => {
    setRecents([{ name: 'doomed', root: '/ws/doomed', last_used: 1 }])
    mockedApi.listProjects.mockResolvedValue({ projects: [{ name: 'doomed', root: '/ws/doomed' }] })
    mockedApi.deleteProject.mockResolvedValue({ deleted: 'doomed' })
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<ProjectSwitcher value='doomed' onChange={onChange} workspace='/ws' />)
    const initial = JSON.parse(window.localStorage.getItem(RECENT_PROJECTS_KEY) ?? '[]') as RecentProject[]
    expect(initial.map((r) => r.name)).toContain('doomed')
    await user.click(screen.getByTitle('Remove project from this session'))
    expect(mockedApi.deleteProject).toHaveBeenCalledWith('doomed')
    const after = JSON.parse(window.localStorage.getItem(RECENT_PROJECTS_KEY) ?? '[]') as RecentProject[]
    expect(after.map((r) => r.name)).not.toContain('doomed')
    expect(onChange).toHaveBeenCalledWith(null)
    confirmSpy.mockRestore()
  })
})

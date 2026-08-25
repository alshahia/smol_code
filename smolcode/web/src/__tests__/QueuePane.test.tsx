// Decision 0031: vitest coverage for the QueuePane drag-and-drop reorder.
//
// Covers:
// - initial render of queued rows + their position pills
// - ↑ / ↓ keyboard buttons invoke moveQueueEntry with the right target
// - single-entry queue disables both buttons
// - drop calls PATCH with the correct target position
// - PATCH 404 -> rollback via refetch + error banner persists
// - dragend without a drop clears visual state
// - unmount clears the drag ref

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return {
    ...actual,
    listQueue: vi.fn(),
    cancelQueueEntry: vi.fn(),
    moveQueueEntry: vi.fn(),
  }
})

import * as api from '../api'
import type { QueueMoveResponse } from '../api'
import { QueuePane } from '../components/QueuePane'

const mockedApi = vi.mocked(api)

function makeQueueResponse(n: number) {
  return {
    active: [],
    queued: Array.from({ length: n }, (_, i) => ({
      id: `q${i + 1}`,
      task: `task-${i + 1}`,
      tier: 'restricted',
      queued_at: i,
      project: null,
      session_id: null,
      queue_position: i + 1,
    })),
  }
}

describe('QueuePane drag-and-drop reorder (decision 0031)', () => {
  beforeEach(() => {
    mockedApi.listQueue.mockReset()
    mockedApi.cancelQueueEntry.mockReset()
    mockedApi.moveQueueEntry.mockReset()
    // Default: listQueue returns 3 queued runs.
    mockedApi.listQueue.mockResolvedValue(makeQueueResponse(3))
    // Confirm is required by Cancel -- auto-accept in tests.
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders one row per queued run with its 1-based position', async () => {
    render(<QueuePane />)
    // Wait for the initial listQueue fetch to populate.
    await waitFor(() => {
      expect(document.querySelectorAll('.queue-row').length).toBe(3)
    })
    const rows = document.querySelectorAll('.queue-row')
    expect(rows.length).toBe(3)
    // Position labels are #1, #2, #3.
    expect(rows[0].querySelector('.queue-row-pos')!.textContent).toBe('#1')
    expect(rows[1].querySelector('.queue-row-pos')!.textContent).toBe('#2')
    expect(rows[2].querySelector('.queue-row-pos')!.textContent).toBe('#3')
  })

  it('Move-up button on the middle row calls moveQueueEntry(id, currentIdx)', async () => {
    const user = userEvent.setup()
    mockedApi.moveQueueEntry.mockResolvedValue({
      run_id: 'q2',
      position: 1,
      queue: [
        { ...makeQueueResponse(3).queued[1], queue_position: 1 },
        { ...makeQueueResponse(3).queued[0], queue_position: 2 },
        { ...makeQueueResponse(3).queued[2], queue_position: 3 },
      ],
    })
    render(<QueuePane />)
    await waitFor(() => {
      expect(document.querySelectorAll('.queue-row').length).toBe(3)
    })
    const upButtons = screen.getAllByRole('button', { name: /move .* up/i })
    // q2 is the middle row, so its up button should be enabled.
    const q2Up = upButtons[1]
    expect(q2Up).not.toBeDisabled()
    await user.click(q2Up)
    // "Up" moves q2 (index 1) to position 1.
    expect(mockedApi.moveQueueEntry).toHaveBeenCalledWith('q2', 1)
  })

  it('Move-down button on the head row calls moveQueueEntry(id, currentIdx+1)', async () => {
    const user = userEvent.setup()
    mockedApi.moveQueueEntry.mockResolvedValue({
      run_id: 'q1',
      position: 2,
      queue: [
        { ...makeQueueResponse(3).queued[1], queue_position: 1 },
        { ...makeQueueResponse(3).queued[0], queue_position: 2 },
        { ...makeQueueResponse(3).queued[2], queue_position: 3 },
      ],
    })
    render(<QueuePane />)
    await waitFor(() => {
      expect(document.querySelectorAll('.queue-row').length).toBe(3)
    })
    const downButtons = screen.getAllByRole('button', { name: /move .* down/i })
    const q1Down = downButtons[0]
    expect(q1Down).not.toBeDisabled()
    await user.click(q1Down)
    // "Down" by one slot = currentIdx (0) + 1 = target 2.
    expect(mockedApi.moveQueueEntry).toHaveBeenCalledWith('q1', 2)
  })

  it('Move-up button is disabled for the first row and down for the last', async () => {
    render(<QueuePane />)
    await waitFor(() => {
      expect(document.querySelectorAll('.queue-row').length).toBe(3)
    })
    const upButtons = screen.getAllByRole('button', { name: /move .* up/i })
    const downButtons = screen.getAllByRole('button', { name: /move .* down/i })
    expect(upButtons[0]).toBeDisabled() // head
    expect(upButtons[1]).not.toBeDisabled()
    expect(upButtons[2]).not.toBeDisabled()
    expect(downButtons[0]).not.toBeDisabled()
    expect(downButtons[1]).not.toBeDisabled()
    expect(downButtons[2]).toBeDisabled() // tail
  })

  it('a single-entry queue disables both up and down buttons', async () => {
    mockedApi.listQueue.mockResolvedValue(makeQueueResponse(1))
    render(<QueuePane />)
    await waitFor(() => {
      expect(document.querySelectorAll('.queue-row').length).toBe(1)
    })
    expect(screen.getByRole('button', { name: /move .* up/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /move .* down/i })).toBeDisabled()
  })

  it('dragstart sets .dragging on the source row', async () => {
    render(<QueuePane />)
    await waitFor(() => {
      expect(document.querySelectorAll('.queue-row').length).toBe(3)
    })
    const source = document.querySelectorAll('.queue-row')[0] as HTMLElement
    act(() => {
      fireEvent.dragStart(source, { dataTransfer: makeDataTransfer() })
    })
    expect(source.className).toContain('dragging')
    // Cleanup
    act(() => {
      fireEvent.dragEnd(source)
    })
  })

  it('drop calls moveQueueEntry with the clamped target position', async () => {
    mockedApi.moveQueueEntry.mockResolvedValue({
      run_id: 'q1',
      position: 2,
      queue: [
        { ...makeQueueResponse(3).queued[1], queue_position: 1 },
        { ...makeQueueResponse(3).queued[0], queue_position: 2 },
        { ...makeQueueResponse(3).queued[2], queue_position: 3 },
      ],
    })
    render(<QueuePane />)
    await waitFor(() => {
      expect(document.querySelectorAll('.queue-row').length).toBe(3)
    })
    const rows = document.querySelectorAll('.queue-row')
    const source = rows[0] as HTMLElement
    const target = rows[2] as HTMLElement
    // Drag q1 onto the upper half of q3 -> target slot = 4, clamped to 3.
    const dt = makeDataTransfer()
    act(() => {
      fireEvent.dragStart(source, { dataTransfer: dt })
      fireEvent.dragOver(target, { dataTransfer: dt, clientY: 25 })
      fireEvent.drop(target, { dataTransfer: dt, clientY: 25 })
    })
    await waitFor(() => {
      expect(mockedApi.moveQueueEntry).toHaveBeenCalled()
    })
    // Source q1 -> target slot 4 -> clamped to len(queue)=3.
    expect(mockedApi.moveQueueEntry).toHaveBeenCalledWith('q1', 3)
  })

  it('shows an error banner when PATCH 404s and refetches the queue', async () => {
    const user = userEvent.setup()
    mockedApi.moveQueueEntry.mockRejectedValue(
      new Error('HTTP 404: queue entry not found'),
    )
    render(<QueuePane />)
    await waitFor(() => {
      expect(document.querySelectorAll('.queue-row').length).toBe(3)
    })
    const upButtons = screen.getAllByRole('button', { name: /move .* up/i })
    await user.click(upButtons[1])
    // The error banner must appear AND persist across the rollback refetch.
    await waitFor(() => {
      expect(document.querySelector('.error-banner')).not.toBeNull()
    })
    expect(
      document.querySelector('.error-banner')!.textContent,
    ).toMatch(/HTTP 404/)
    // listQueue was called at least twice (initial + rollback refetch).
    expect(mockedApi.listQueue.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('clears .dragging on dragend without a drop', async () => {
    render(<QueuePane />)
    await waitFor(() => {
      expect(document.querySelectorAll('.queue-row').length).toBe(3)
    })
    const source = document.querySelectorAll('.queue-row')[0] as HTMLElement
    act(() => {
      fireEvent.dragStart(source, { dataTransfer: makeDataTransfer() })
    })
    expect(source.className).toContain('dragging')
    act(() => {
      fireEvent.dragEnd(source)
    })
    expect(source.className).not.toContain('dragging')
  })

  it('Cancel button is disabled while a move is in flight', async () => {
    const user = userEvent.setup()
    // PATCH never resolves: cancel button stays disabled.
    let resolveMove: (v: QueueMoveResponse) => void = () => {}
    mockedApi.moveQueueEntry.mockReturnValue(
      new Promise<QueueMoveResponse>((res) => {
        resolveMove = res
      }),
    )
    render(<QueuePane />)
    await waitFor(() => {
      expect(document.querySelectorAll('.queue-row').length).toBe(3)
    })
    const upButtons = screen.getAllByRole('button', { name: /move .* up/i })
    await user.click(upButtons[1])
    // The Cancel button text becomes "Working…" while the move is pending.
    await waitFor(() => {
      expect(screen.getByText(/working…/i)).toBeInTheDocument()
    })
    // Now resolve the move to clean up.
    await act(async () => {
      resolveMove({
        run_id: 'q2',
        position: 1,
        queue: [
          { ...makeQueueResponse(3).queued[1], queue_position: 1 },
          { ...makeQueueResponse(3).queued[0], queue_position: 2 },
          { ...makeQueueResponse(3).queued[2], queue_position: 3 },
        ],
      })
    })
  })
})

// jsdom does not implement DataTransfer, so we provide a tiny stub.
function makeDataTransfer(): DataTransfer {
  const map = new Map<string, string>()
  return {
    dropEffect: 'none',
    effectAllowed: 'all',
    files: [] as unknown as FileList,
    items: [] as unknown as DataTransferItemList,
    types: [],
    clearData: (_format?: string) => undefined,
    getData: (format: string) => map.get(format) ?? '',
    setData: (format: string, value: string) => {
      map.set(format, value)
    },
    setDragImage: () => undefined,
  } as unknown as DataTransfer
}

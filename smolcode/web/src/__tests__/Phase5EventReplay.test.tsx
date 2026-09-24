// Phase 5 (ADR 0040 section 4) -- finished-run history hydration.
//
// Selecting a completed run used to show "Waiting for events..." forever:
// the SSE stream had already finished emitting before the user selected
// the run, so the client connected, received nothing, and waited.
//
// Note these tests pass status explicitly. With no status prop the
// component keeps its pre-Phase-5 behaviour (open the stream), which is
// what the older EventStream.test.tsx suite covers.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { EventStream } from '../components/EventStream'

const SNAPSHOT_EVENTS = [
  { type: 'run.started', run_id: 'r1', task: 'do the thing' },
  { type: 'step.action', run_id: 'r1', tool: 'write_file' },
  { type: 'run.ended', run_id: 'r1', status: 'done', result: 'all good' },
]

class FakeEventSource {
  static instances: FakeEventSource[] = []
  url: string
  readyState = 1
  onerror: (() => void) | null = null
  onopen: (() => void) | null = null
  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }
  addEventListener() {}
  removeEventListener() {}
  close() {}
  static reset() {
    FakeEventSource.instances = []
  }
}

function stubSnapshot(snap: unknown) {
  vi.stubGlobal(
    'fetch',
    (input: RequestInfo | URL) => {
      const u = typeof input === 'string' ? input : String((input as Request).url ?? input)
      if (u.includes('/events/snapshot')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          text: () => Promise.resolve(JSON.stringify(snap)),
          json: () => Promise.resolve(snap),
        })
      }
      return Promise.reject(new Error('unexpected fetch: ' + u))
    },
  )
}

beforeEach(() => {
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ADR0040-4 finished-run history', () => {
  it('renders the recorded log for a finished run without opening a stream', async () => {
    stubSnapshot({ events: SNAPSHOT_EVENTS, status: 'done' })
    const { container } = render(<EventStream runId={'r1'} status={'done'} />)

    // Every event row renders its type in a .stream-kind badge.
    await waitFor(() => {
      expect(container.querySelectorAll('.stream-row').length).toBe(SNAPSHOT_EVENTS.length)
    })
    expect(container.textContent).toContain('run.started')
    expect(container.textContent).toContain('step.action')
    expect(container.textContent).toContain('run.ended')

    // The recorded history is visible, not a waiting placeholder.
    expect(screen.queryByText('Waiting for events...')).toBeNull()

    // And no EventSource was opened for a run the server already finished.
    expect(FakeEventSource.instances).toHaveLength(0)
  })

  it('reports the terminal status instead of a connection state', async () => {
    stubSnapshot({ events: [], status: 'error' })
    render(<EventStream runId={'r1'} status={'error'} />)
    await waitFor(() => {
      expect(screen.getByText('SSE: error')).toBeTruthy()
    })
  })

  it('does not open a stream for a stopped run either', async () => {
    stubSnapshot({ events: [], status: 'stopped' })
    render(<EventStream runId={'r1'} status={'stopped'} />)
    await waitFor(() => {
      expect(screen.getByText('SSE: stopped')).toBeTruthy()
    })
    expect(FakeEventSource.instances).toHaveLength(0)
  })

  it('opens a live stream for a non-terminal run and never fetches a snapshot', async () => {
    const fetchSpy = vi.fn(() => Promise.reject(new Error('snapshot must not be requested')))
    vi.stubGlobal('fetch', fetchSpy)
    render(<EventStream runId={'r2'} status={'running'} />)

    await waitFor(() => {
      expect(FakeEventSource.instances).toHaveLength(1)
    })
    expect(FakeEventSource.instances[0].url).toContain('/api/runs/r2/events')
    // No snapshot round trip on the live path. events_snapshot reads
    // events_log while subscribe drains a separate queue, so fetching
    // both would render any event published in between twice.
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('STREAMS when status is null -- the run is live but not yet resolved', async () => {
    // Regression guard. App renders EventStream as soon as activeRunId is
    // set, but activeRun is filled by the runs poll, so a run the list has
    // not caught up with leaves status null indefinitely. The approval e2e
    // suite is exactly that shape (runs: [], status awaiting_approval),
    // and an approval.requested frame only ever arrives over the stream.
    // Treating null as 'wait for a status' silently removed the approval
    // modal, which is strictly worse than a brief connection to a run
    // that turns out to be finished.
    const fetchSpy = vi.fn(() => Promise.reject(new Error('no snapshot')))
    vi.stubGlobal('fetch', fetchSpy)
    render(<EventStream runId={'r-live'} status={null} />)

    await waitFor(() => {
      expect(FakeEventSource.instances).toHaveLength(1)
    })
    expect(FakeEventSource.instances[0].url).toContain('/api/runs/r-live/events')
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('treats a missing status as live, preserving pre-Phase-5 behaviour', async () => {
    vi.stubGlobal('fetch', () => Promise.reject(new Error('nope')))
    render(<EventStream runId={'r3'} />)
    await waitFor(() => {
      expect(FakeEventSource.instances).toHaveLength(1)
    })
  })

  it('shows an error state rather than hanging when the snapshot fails', async () => {
    vi.stubGlobal('fetch', () => Promise.reject(new Error('offline')))
    render(<EventStream runId={'r4'} status={'done'} />)
    await waitFor(() => {
      expect(screen.getByText('SSE: error')).toBeTruthy()
    })
    expect(FakeEventSource.instances).toHaveLength(0)
  })
})

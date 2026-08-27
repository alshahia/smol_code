// Decision 0030: vitest coverage for the SSE dispatch fix.
//
// EventSource is replaced with a stub that records addEventListener
// calls and lets us trigger typed handlers manually. We then verify:
//
// 1. addEventListener is called once per known BE event type (i.e.
//    the SPA no longer relies on onmessage for named events).
// 2. A MessageEvent on approval.requested correctly drives
//    onApprovalRequest.
// 3. A MessageEvent on diff.proposed correctly drives
//    onDiffProposed.
// 4. A MessageEvent on run.ended correctly drives onFinal.
// 5. A MessageEvent on end closes the EventSource.
// 6. Malformed JSON is dropped silently without crashing the SPA.
// 7. The EventSource is closed on unmount.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render } from '@testing-library/react'

import { EventStream } from '../components/EventStream'

interface RecordedHandler {
  type: string
  fn: (ev: MessageEvent) => void
}

class FakeEventSource {
  static instances: FakeEventSource[] = []
  url: string
  readyState: number = 0 // CONNECTING
  onopen: ((ev: Event) => void) | null = null
  onerror: ((ev: Event) => void) | null = null
  onmessage: ((ev: MessageEvent) => void) | null = null
  private listeners: RecordedHandler[] = []

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, fn: (ev: MessageEvent) => void): void {
    this.listeners.push({ type, fn })
  }

  removeEventListener(type: string, fn: (ev: MessageEvent) => void): void {
    this.listeners = this.listeners.filter((h) => !(h.type === type && h.fn === fn))
  }

  // Test-only accessor (read by the assertions below).
  getHandlers(type: string): RecordedHandler[] {
    return this.listeners.filter((h) => h.type === type)
  }

  getRegisteredTypes(): string[] {
    return this.listeners.map((h) => h.type)
  }

  close(): void {
    this.readyState = 2 // CLOSED
  }

  // Test helper: fire a typed event the way the browser would.
  dispatch(type: string, data: unknown): void {
    const rec = this.listeners.find((h) => h.type === type)
    if (!rec) throw new Error('no listener registered for ' + type)
    rec.fn({ data: typeof data === 'string' ? data : JSON.stringify(data) } as MessageEvent)
  }

  static reset(): void {
    FakeEventSource.instances = []
  }
}

const KNOWN_TYPES = [
  'run.started',
  'run.ended',
  'plan.step',
  'step.action',
  'step.final_answer',
  'approval.requested',
  'approval.decided',
  'diff.proposed',
  'diff.resolved',
  'error',
  'subagent.started',
  'subagent.ended',
  'run.paused',
  'run.resumed',
  'end',
]

beforeEach(() => {
  FakeEventSource.reset()
  // jsdom ships EventSource as undefined; install our stub globally.
  ;(globalThis as unknown as { EventSource: unknown }).EventSource = FakeEventSource
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('EventStream SSE dispatch (decision 0030)', () => {
  it('registers addEventListener for every known BE event type', () => {
    render(<EventStream runId="r-1" />)
    const es = FakeEventSource.instances[0]
    expect(es).toBeDefined()
    const registered = new Set(es.getRegisteredTypes())
    for (const t of KNOWN_TYPES) {
      expect(registered.has(t)).toBe(true)
    }
    expect(es.onmessage).toBeNull() // named events go through typed listeners
  })

  it('opens the EventSource at /api/runs/{id}/events', () => {
    render(<EventStream runId="abc-123" />)
    expect(FakeEventSource.instances[0].url).toBe('/api/runs/abc-123/events')
  })

  it('dispatches approval.requested to onApprovalRequest', () => {
    const onApprovalRequest = vi.fn()
    render(<EventStream runId="r-1" onApprovalRequest={onApprovalRequest} />)
    const es = FakeEventSource.instances[0]
    act(() => {
      es.dispatch('approval.requested', {
        decision_id: 'd-1',
        tool: 'shell',
        args: { cmd: 'rm -rf /' },
        summary: 'destructive op',
      })
    })
    // Phase 3 F3 (decision 0037) extended onApprovalRequest with trailing
    // (kind, absoluteTarget?, effectiveCwd?, allowedActions?). The destructive
    // approval carries kind='destructive' and nulls for the outside-root fields.
    expect(onApprovalRequest).toHaveBeenCalledWith(
      'd-1',
      'shell',
      { cmd: 'rm -rf /' },
      'destructive op',
      'destructive',
      null,
      null,
      null,
    )
  })

  it('dispatches diff.proposed to onDiffProposed with every field', () => {
    const onDiffProposed = vi.fn()
    render(<EventStream runId="r-1" onDiffProposed={onDiffProposed} />)
    const es = FakeEventSource.instances[0]
    act(() => {
      es.dispatch('diff.proposed', {
        decision_id: 'd-2',
        tool: 'write_file',
        args: { path: '/x' },
        summary: 'edit',
        path: '/abs/x',
        rel_path: 'x',
        before: 'a',
        after: 'b',
        raw_diff: '--- a\n+++ b',
        hunks: [],
        stats: { added: 1, removed: 1, same: 0, changed: true },
      })
    })
    expect(onDiffProposed).toHaveBeenCalledWith(
      'd-2',
      'write_file',
      { path: '/x' },
      'edit',
      '/abs/x',
      'x',
      'a',
      'b',
      '--- a\n+++ b',
      [],
      { added: 1, removed: 1, same: 0, changed: true },
    )
  })

  it('dispatches run.ended to onFinal', () => {
    const onFinal = vi.fn()
    render(<EventStream runId="r-1" onFinal={onFinal} />)
    const es = FakeEventSource.instances[0]
    act(() => {
      es.dispatch('run.ended', { result: 'ok', error: null, status: 'done' })
    })
    expect(onFinal).toHaveBeenCalledWith('ok', null)
  })

  it('closes the EventSource when an end frame arrives', () => {
    render(<EventStream runId="r-1" />)
    const es = FakeEventSource.instances[0]
    expect(es.readyState).toBe(0)
    act(() => {
      es.dispatch('end', { run_id: 'r-1', status: 'done' })
    })
    expect(es.readyState).toBe(2) // CLOSED
  })

  it('silently drops malformed JSON without crashing', () => {
    const onApprovalRequest = vi.fn()
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<EventStream runId="r-1" onApprovalRequest={onApprovalRequest} />)
    const es = FakeEventSource.instances[0]
    act(() => {
      es.dispatch('approval.requested', '{not valid json')
    })
    expect(onApprovalRequest).not.toHaveBeenCalled()
    expect(consoleSpy).not.toHaveBeenCalled()
  })

  it('groups subagent.started / subagent.ended events into a nested block', () => {
    const { container } = render(<EventStream runId="r-1" />)
    const es = FakeEventSource.instances[0]
    act(() => {
      es.dispatch('subagent.started', {
        subagent_id: 'sub-1',
        tier: 'elevated',
      })
      es.dispatch('step.action', { thought: 'doing thing' })
      es.dispatch('subagent.ended', {
        subagent_id: 'sub-1',
        status: 'done',
        duration_s: 1.5,
      })
    })
    expect(container.querySelector('.stream-subagent')).not.toBeNull()
    expect(container.querySelector('.stream-row-nested')).not.toBeNull()
  })

  it('closes the EventSource on unmount', () => {
    const { unmount } = render(<EventStream runId="r-1" />)
    const es = FakeEventSource.instances[0]
    expect(es.readyState).toBe(0)
    unmount()
    expect(es.readyState).toBe(2)
  })

  it('reconnects (fresh EventSource) when runId changes', () => {
    const { rerender } = render(<EventStream runId="r-1" />)
    const first = FakeEventSource.instances[0]
    rerender(<EventStream runId="r-2" />)
    const second = FakeEventSource.instances[1]
    expect(first.readyState).toBe(2)
    expect(second).toBeDefined()
    expect(second.url).toBe('/api/runs/r-2/events')
  })
})
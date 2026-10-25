// Command palette: the keyboard door to every surface that used to be a
// permanent pane. It searches actions and runs; Enter executes, arrows move.

import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { RunSummary } from '../../api'
import { Icon } from './Icon'

export interface PaletteAction {
  id: string
  label: string
  hint?: string
  shortcut?: string
  run: () => void
}

interface Props {
  open: boolean
  actions: PaletteAction[]
  runs: RunSummary[]
  onClose: () => void
  onSelectRun: (runId: string) => void
}

export function CommandPalette({ open, actions, runs, onClose, onSelectRun }: Props) {
  const [query, setQuery] = useState('')
  const [index, setIndex] = useState(0)
  const panelRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  const needle = query.trim().toLowerCase()
  const filteredActions = useMemo(
    () =>
      actions.filter(
        (a) =>
          !needle ||
          a.label.toLowerCase().includes(needle) ||
          (a.hint || '').toLowerCase().includes(needle),
      ),
    [actions, needle],
  )
  const filteredRuns = useMemo(
    () =>
      runs
        .filter(
          (r) =>
            !needle ||
            r.task.toLowerCase().includes(needle) ||
            r.id.toLowerCase().includes(needle),
        )
        .slice(0, 7),
    [runs, needle],
  )
  const items = useMemo(
    () => [
      ...filteredActions.map((a) => ({ kind: 'action' as const, action: a })),
      ...filteredRuns.map((r) => ({ kind: 'run' as const, run: r })),
    ],
    [filteredActions, filteredRuns],
  )

  useEffect(() => {
    if (!open) return
    setQuery('')
    setIndex(0)
    window.setTimeout(() => inputRef.current?.focus(), 0)
    const previous = document.activeElement as HTMLElement | null
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCloseRef.current()
      }
      if (event.key === 'Tab') {
        const panel = panelRef.current
        if (!panel) return
        const focusables = Array.from(
          panel.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled])'),
        )
        if (focusables.length === 0) return
        const first = focusables[0]
        const last = focusables[focusables.length - 1]
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault()
          last.focus()
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      previous?.focus?.()
    }
  }, [open])

  if (!open || typeof document === 'undefined') return null

  const choose = (item: (typeof items)[number]) => {
    onClose()
    if (item.kind === 'action') item.action.run()
    else onSelectRun(item.run.id)
  }

  return createPortal(
    <>
      <div className="palette-backdrop" aria-hidden="true" onClick={onClose} />
      <section
        ref={panelRef}
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
      >
        <div className="palette-input">
          <Icon name="search" size={16} />
          <input
            ref={inputRef}
            value={query}
            placeholder="Search commands and runs"
            aria-label="Search commands and runs"
            onChange={(event) => {
              setQuery(event.target.value)
              setIndex(0)
            }}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') {
                event.preventDefault()
                setIndex((i) => Math.min(i + 1, items.length - 1))
              } else if (event.key === 'ArrowUp') {
                event.preventDefault()
                setIndex((i) => Math.max(i - 1, 0))
              } else if (event.key === 'Enter' && items[index]) {
                event.preventDefault()
                choose(items[index])
              }
            }}
          />
          <span className="esc">esc</span>
        </div>
        <div className="palette-list" role="listbox" aria-label="Commands">
          {items.length === 0 ? <div className="palette-empty">No matching command or run.</div> : null}
          {filteredActions.length > 0 ? <div className="palette-group">Actions</div> : null}
          {filteredActions.map((action) => {
            const i = items.findIndex((item) => item.kind === 'action' && item.action.id === action.id)
            return (
              <button
                key={action.id}
                type="button"
                className="palette-item"
                role="option"
                aria-selected={i === index}
                onMouseEnter={() => setIndex(i)}
                onClick={() => choose({ kind: 'action', action })}
              >
                <Icon name={iconFor(action.id)} size={14} />
                <span>{action.label}</span>
                {action.hint ? <span className="pmeta">{action.hint}</span> : null}
                {action.shortcut ? <span className="short">{action.shortcut}</span> : null}
              </button>
            )
          })}
          {filteredRuns.length > 0 ? <div className="palette-group">Runs</div> : null}
          {filteredRuns.map((run) => {
            const i = items.findIndex((item) => item.kind === 'run' && item.run.id === run.id)
            return (
              <button
                key={run.id}
                type="button"
                className="palette-item"
                role="option"
                aria-selected={i === index}
                onMouseEnter={() => setIndex(i)}
                onClick={() => choose({ kind: 'run', run })}
              >
                <span className={'status-dot ' + run.status} aria-hidden="true" />
                <span className="run-label">{run.task}</span>
                <span className="pmeta">{run.id}</span>
              </button>
            )
          })}
        </div>
      </section>
    </>,
    document.body,
  )
}

function iconFor(id: string) {
  if (id === 'new-run') return 'plus' as const
  if (id === 'runs') return 'menu' as const
  if (id === 'queue') return 'queue' as const
  if (id === 'sessions') return 'panel' as const
  if (id === 'audit') return 'chain' as const
  if (id === 'context') return 'dots' as const
  if (id === 'usage') return 'panel' as const
  if (id === 'help') return 'help' as const
  if (id === 'files') return 'folder' as const
  if (id === 'changes') return 'file' as const
  if (id === 'console') return 'command' as const
  if (id === 'trace') return 'play' as const
  return 'arrow' as const
}

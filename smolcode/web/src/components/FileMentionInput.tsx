// FileMentionInput: textarea with @-trigger autocomplete for file
// paths from the project tree. Replaces the bare <textarea> in
// <RunComposer>.
//
// Phase 2 (decision 0025 §6.4 A5): the user types ``@`` anywhere in
// the task; an autocomplete dropdown opens with paths from the active
// project tree. Selecting a path inserts ``@<path>`` into the input.
// The actual file-content inlining happens server-side in
// ``agent_runner._attach_mentions`` once the run starts.

import { useEffect, useMemo, useRef, useState } from 'react'
import { getWorkspaceTree } from '../api'
import { parseMentions, suggestPaths } from '../lib/mentions'

interface Props {
  value: string
  onChange: (next: string) => void
  /** Project name to scope the autocomplete against; null = legacy workspace. */
  project: string | null
  disabled?: boolean
  rows?: number
  placeholder?: string
}

interface AutocompleteState {
  /** Position in the input where the ``@`` token starts. */
  start: number
  /** Position one past the last typed char. */
  end: number
  /** Text after ``@`` the user has typed (the prefix). */
  prefix: string
  /** Suggestions to display. */
  options: string[]
  /** Currently focused suggestion index. */
  activeIndex: number
}

export function FileMentionInput({
  value,
  onChange,
  project,
  disabled,
  rows = 4,
  placeholder = 'Describe the task for the agent... use @path to attach a file',
}: Props) {
  const ref = useRef<HTMLTextAreaElement | null>(null)
  const [paths, setPaths] = useState<string[]>([])
  const [autocomplete, setAutocomplete] = useState<AutocompleteState | null>(null)

  // Fetch the project file tree once on mount + whenever the active
  // project changes. Cheap; capped at ~5K entries server-side.
  useEffect(() => {
    let cancelled = false
    getWorkspaceTree(5000, 10, project ?? undefined)
      .then((res) => {
        if (cancelled) return
        // Only the leaf paths are useful for mentions.
        const leaves = res.entries.filter((e) => !e.is_dir).map((e) => e.rel_path)
        setPaths(leaves)
      })
      .catch(() => setPaths([]))
    return () => {
      cancelled = true
    }
  }, [project])

  // Update autocomplete whenever the value or cursor changes.
  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const next = e.target.value
    onChange(next)
    updateAutocomplete(next, e.target.selectionStart ?? next.length)
  }

  const handleSelect = (e: React.SyntheticEvent<HTMLTextAreaElement>) => {
    const tgt = e.currentTarget
    updateAutocomplete(tgt.value, tgt.selectionStart ?? tgt.value.length)
  }

  const updateAutocomplete = (text: string, cursor: number) => {
    // Find the @ token immediately preceding the cursor.
    let i = cursor - 1
    while (i >= 0) {
      const ch = text[i]
      if (ch === '@') {
        // Make sure there's no word char before this @ (avoid email-like matches).
        const before = i > 0 ? text[i - 1] : ''
        if (before && /[A-Za-z0-9_]/.test(before)) {
          setAutocomplete(null)
          return
        }
        const prefix = text.slice(i + 1, cursor)
        if (/[^A-Za-z0-9_./\-]/.test(prefix)) {
          setAutocomplete(null)
          return
        }
        const options = suggestPaths(paths, prefix, 8)
        if (options.length === 0 && prefix.length === 0) {
          setAutocomplete(null)
          return
        }
        setAutocomplete({
          start: i,
          end: cursor,
          prefix,
          options,
          activeIndex: 0,
        })
        return
      }
      if (/[\s\n,]/.test(ch ?? '')) {
        break
      }
      i -= 1
    }
    setAutocomplete(null)
  }

  const applySuggestion = (path: string) => {
    if (!autocomplete) return
    const before = value.slice(0, autocomplete.start)
    const after = value.slice(autocomplete.end)
    const inserted = '@' + path + ' '
    const next = before + inserted + after
    onChange(next)
    // Move cursor to right after the inserted token.
    requestAnimationFrame(() => {
      if (ref.current) {
        const pos = before.length + inserted.length
        ref.current.focus()
        ref.current.setSelectionRange(pos, pos)
      }
    })
    setAutocomplete(null)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!autocomplete || autocomplete.options.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setAutocomplete({
        ...autocomplete,
        activeIndex: (autocomplete.activeIndex + 1) % autocomplete.options.length,
      })
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setAutocomplete({
        ...autocomplete,
        activeIndex:
          (autocomplete.activeIndex - 1 + autocomplete.options.length) %
          autocomplete.options.length,
      })
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault()
      const opt = autocomplete.options[autocomplete.activeIndex]
      if (opt) applySuggestion(opt)
    } else if (e.key === 'Escape') {
      setAutocomplete(null)
    }
  }

  // Highlight mention chips (visual: bold + accent color). Cheap --
  // runs on every keystroke but the task string is small.
  const mentionCount = useMemo(() => parseMentions(value).length, [value])

  return (
    <div className="file-mention-input">
      <textarea
        ref={ref}
        className="task-input"
        placeholder={placeholder}
        value={value}
        onChange={handleChange}
        onSelect={handleSelect}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        rows={rows}
      />
      {autocomplete && autocomplete.options.length > 0 && (
        <div className="mention-autocomplete" role="listbox">
          {autocomplete.options.map((p, i) => (
            <button
              type="button"
              key={p}
              role="option"
              aria-selected={i === autocomplete.activeIndex}
              className={
                'mention-suggestion' + (i === autocomplete.activeIndex ? ' active' : '')
              }
              onMouseDown={(ev) => {
                ev.preventDefault()
                applySuggestion(p)
              }}
              onMouseEnter={() =>
                setAutocomplete({ ...autocomplete, activeIndex: i })
              }
            >
              {p}
            </button>
          ))}
        </div>
      )}
      {mentionCount > 0 && (
        <div className="muted small mention-counter">
          {mentionCount} file mention{mentionCount === 1 ? '' : 's'} attached
        </div>
      )}
    </div>
  )
}

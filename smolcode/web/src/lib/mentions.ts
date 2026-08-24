// lib/mentions: parse @path tokens from a task string + autocomplete
// against the project file tree.
//
// Phase 2 (decision 0025 §6.4 A5): the SPA shows an autocomplete
// dropdown when the user types ``@`` in the task input. This module
// is the client-side helper -- the backend's ``_attach_mentions`` does
// the actual file-content inlining (security-critical path resolution
// happens server-side).
//
// Mentions inside fenced code blocks (`` ``` ... ``` ``) are ignored,
// matching the backend's parser regex. Tokens are terminated by any
// character outside ``[A-Za-z0-9_./-]``.

const MENTION_RE = /(?:^|[^\w])@([A-Za-z0-9_./\-]+)/g
const FENCE_RE = /```[^\n]*\n.*?```/gs

export interface MentionToken {
  /** Position in the original task string where ``@`` appears. */
  start: number
  /** Position one past the last char of the path. */
  end: number
  /** The path text (without the leading ``@``). */
  path: string
  /** The raw ``@path`` substring. */
  raw: string
}

export function parseMentions(task: string): MentionToken[] {
  if (!task) return []
  // Strip fenced blocks (replace with same-length whitespace) so
  // offsets stay aligned with the original input.
  const masked = task.replace(FENCE_RE, (m) => ' '.repeat(m.length))
  const out: MentionToken[] = []
  for (const m of masked.matchAll(MENTION_RE)) {
    const path = m[1]
    const start = (m.index ?? 0) + (m[0].length - path.length - 1)
    out.push({
      start,
      end: start + 1 + path.length, // include the leading '@'
      path,
      raw: '@' + path,
    })
  }
  return out
}

/**
 * Filter the project's file list down to paths that start with the
 * given prefix. Used by <FileMentionInput> to populate the autocomplete
 * dropdown as the user types after ``@``.
 *
 * @param paths  All file paths (relative to the project root).
 * @param prefix The text the user has typed after ``@`` (no leading @).
 * @param limit  Max number of suggestions to return.
 */
export function suggestPaths(
  paths: readonly string[],
  prefix: string,
  limit = 8,
): string[] {
  const lp = prefix.toLowerCase()
  const matches = paths.filter((p) => p.toLowerCase().includes(lp))
  // Prefer exact-prefix matches first.
  matches.sort((a, b) => {
    const aStart = a.toLowerCase().startsWith(lp) ? 0 : 1
    const bStart = b.toLowerCase().startsWith(lp) ? 0 : 1
    if (aStart !== bStart) return aStart - bStart
    return a.length - b.length
  })
  return matches.slice(0, limit)
}

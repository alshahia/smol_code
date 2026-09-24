export function isOutsideWorkspace(target: string, workspace: string | null | undefined): boolean {
  const t = target.trim(); if (!t) return false
  const ws = (workspace ?? '').trim(); if (!ws) return false
  const norm = (p: string) => p.replace(/[\\/]+/g, '/').replace(/\/$/, '').toLowerCase()
  const a = norm(t); const b = norm(ws)
  if (a === b) return false
  const lastA = a.split('/').pop() ?? ''
  if (a === b + '/' + lastA) return false
  return !a.startsWith(b + '/')
}

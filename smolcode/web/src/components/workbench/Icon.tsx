// One line-icon vocabulary for the shell. The sprite is mounted once by
// IconSprite; Icon only references a symbol. No icon font, no emoji.

export type IconName =
  | 'menu'
  | 'search'
  | 'chevron'
  | 'pause'
  | 'stop'
  | 'dots'
  | 'folder'
  | 'file'
  | 'x'
  | 'check'
  | 'shield'
  | 'attach'
  | 'command'
  | 'plus'
  | 'play'
  | 'queue'
  | 'chain'
  | 'panel'
  | 'help'
  | 'copy'
  | 'arrow'

export function Icon({ name, size = 16 }: { name: IconName; size?: number }) {
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <use href={'#i-' + name} />
    </svg>
  )
}

export function IconSprite() {
  return (
    <svg width="0" height="0" aria-hidden="true" focusable="false" style={{ position: 'absolute' }}>
      <symbol id="i-menu" viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16" /></symbol>
      <symbol id="i-search" viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="6.5" /><path d="M16 16l4.5 4.5" /></symbol>
      <symbol id="i-chevron" viewBox="0 0 24 24"><path d="M8 10l4 4 4-4" /></symbol>
      <symbol id="i-pause" viewBox="0 0 24 24"><path d="M9 6v12M15 6v12" /></symbol>
      <symbol id="i-stop" viewBox="0 0 24 24"><rect x="7" y="7" width="10" height="10" rx="1" /></symbol>
      <symbol id="i-dots" viewBox="0 0 24 24"><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></symbol>
      <symbol id="i-folder" viewBox="0 0 24 24"><path d="M3.5 7.5h6l2 2h9v8.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z" /><path d="M3.5 7.5v-1a2 2 0 0 1 2-2h4l2 2" /></symbol>
      <symbol id="i-file" viewBox="0 0 24 24"><path d="M6 3.5h7l5 5V20a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 5 20V5A1.5 1.5 0 0 1 6.5 3.5z" /><path d="M13 3.5V9h5" /></symbol>
      <symbol id="i-x" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18" /></symbol>
      <symbol id="i-check" viewBox="0 0 24 24"><path d="M5 12.5l4.2 4.2L19 7" /></symbol>
      <symbol id="i-shield" viewBox="0 0 24 24"><path d="M12 3.5l7 2.8v5.2c0 4.2-2.9 7.4-7 8.9-4.1-1.5-7-4.7-7-8.9V6.3z" /><path d="M9 12l2 2 4-4" /></symbol>
      <symbol id="i-attach" viewBox="0 0 24 24"><path d="M8.5 12.5l6.6-6.6a3 3 0 0 1 4.2 4.2l-8.2 8.2a4.5 4.5 0 0 1-6.4-6.4l8-8" /></symbol>
      <symbol id="i-command" viewBox="0 0 24 24"><path d="M9 6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3z" /></symbol>
      <symbol id="i-plus" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></symbol>
      <symbol id="i-play" viewBox="0 0 24 24"><path d="M8 5.5l10 6.5-10 6.5z" /></symbol>
      <symbol id="i-queue" viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h10" /><path d="M18 15l2 2-2 2" /></symbol>
      <symbol id="i-chain" viewBox="0 0 24 24"><path d="M9.5 14.5l5-5" /><path d="M7.8 16.2l-1.2 1.2a3.8 3.8 0 0 1-5.4-5.4l2.4-2.4a3.8 3.8 0 0 1 5.4 0" /><path d="M16.2 7.8l1.2-1.2a3.8 3.8 0 0 1 5.4 5.4l-2.4 2.4a3.8 3.8 0 0 1-5.4 0" /></symbol>
      <symbol id="i-panel" viewBox="0 0 24 24"><rect x="3.5" y="4.5" width="17" height="15" rx="1.5" /><path d="M14.5 4.5v15" /></symbol>
      <symbol id="i-help" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5" /><path d="M9.6 9.2a2.6 2.6 0 1 1 3.4 2.5c-.8.3-1 .8-1 1.6" /><path d="M12 17h.01" /></symbol>
      <symbol id="i-copy" viewBox="0 0 24 24"><rect x="8.5" y="8.5" width="11" height="11" rx="1.5" /><path d="M6 15.5H5A1.5 1.5 0 0 1 3.5 14V5A1.5 1.5 0 0 1 5 3.5h9A1.5 1.5 0 0 1 15.5 5v1" /></symbol>
      <symbol id="i-arrow" viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6" /></symbol>
    </svg>
  )
}

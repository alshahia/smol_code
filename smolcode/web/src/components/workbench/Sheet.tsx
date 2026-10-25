// A modal surface with the two Workbench shapes: the dark left sheet used
// for run/session lists, and the vellum drawer/launch sheet used for
// context, audit, usage and a new run. Focus is trapped while open and
// returned to the invoking control on close.

import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Icon } from './Icon'

export type SheetVariant = 'side' | 'drawer' | 'launch'

interface SheetProps {
  open: boolean
  title: string
  subtitle?: string
  variant: SheetVariant
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  wide?: boolean
  label?: string
  className?: string
}

export function Sheet({
  open,
  title,
  subtitle,
  variant,
  onClose,
  children,
  footer,
  wide = false,
  label,
  className = '',
}: SheetProps) {
  const panelRef = useRef<HTMLElement | null>(null)
  const closeRef = useRef<HTMLButtonElement | null>(null)
  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    const panel = panelRef.current
    const focusables = () =>
      Array.from(
        panel?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((el) => el.offsetParent !== null || el === closeRef.current)
    const first = focusables()[0]
    ;(first ?? closeRef.current)?.focus()

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onCloseRef.current()
        return
      }
      if (event.key !== 'Tab') return
      const items = focusables()
      if (items.length === 0) return
      const firstItem = items[0]
      const lastItem = items[items.length - 1]
      if (event.shiftKey && document.activeElement === firstItem) {
        event.preventDefault()
        lastItem.focus()
      } else if (!event.shiftKey && document.activeElement === lastItem) {
        event.preventDefault()
        firstItem.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown, true)
    return () => {
      document.removeEventListener('keydown', onKeyDown, true)
      previous?.focus?.()
    }
  }, [open])

  if (!open || typeof document === 'undefined') return null

  const headClass = variant === 'side' ? 'sheet-head' : variant === 'drawer' ? 'drawer-head' : 'launch-head'
  const panelClass =
    variant === 'side' ? 'sheet' : variant === 'drawer' ? 'drawer' : 'launch'
  const titleId = 'wb-sheet-title'

  return createPortal(
    <>
      <button
        type="button"
        className="scrim"
        tabIndex={-1}
        aria-label={'Close ' + title}
        onClick={() => onCloseRef.current()}
      />
      <section
        ref={panelRef}
        className={[panelClass, wide ? 'drawer-wide' : '', className].filter(Boolean).join(' ')}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-label={label}
      >
        <header className={headClass}>
          <div className="grow">
            <h2 id={titleId}>{title}</h2>
            {subtitle ? <p className="sub">{subtitle}</p> : null}
          </div>
          <button
            ref={closeRef}
            type="button"
            className="close"
            aria-label={'Close ' + title}
            onClick={() => onCloseRef.current()}
          >
            <Icon name="x" size={15} />
          </button>
        </header>
        <div className="sheet-body">{children}</div>
        {footer ? <footer className="sheet-foot">{footer}</footer> : null}
      </section>
    </>,
    document.body,
  )
}

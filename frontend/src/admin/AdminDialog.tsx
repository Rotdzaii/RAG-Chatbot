import { useEffect, useRef } from 'react'
import type { PropsWithChildren } from 'react'
import { gsap } from 'gsap'

export function AdminDialog({ title, children, busy, onClose }: PropsWithChildren<{
  title: string; busy: boolean; onClose: () => void
}>) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = ref.current!
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    dialog.showModal()
    dialog.querySelector<HTMLElement>('[data-dialog-initial-focus]')?.focus()
    const mm = gsap.matchMedia()
    mm.add('(prefers-reduced-motion: no-preference)', () => {
      gsap.fromTo(dialog, { y: 8, autoAlpha: 0.85 }, { y: 0, autoAlpha: 1, duration: 0.18, ease: 'power1.out' })
    })
    return () => { mm.revert(); dialog.close(); previous?.focus() }
  }, [])
  return <dialog className="admin-dialog" ref={ref} aria-labelledby="admin-dialog-title"
    onCancel={event => { event.preventDefault(); if (!busy) onClose() }}>
    <div className="admin-dialog__header"><h2 id="admin-dialog-title">{title}</h2>
      <button type="button" className="admin-icon-button" aria-label="Đóng hộp thoại" disabled={busy} onClick={onClose}>×</button>
    </div>
    <div className="admin-dialog__content">{children}</div>
  </dialog>
}

import { useEffect, useId, useRef, useState } from 'react'
import type { KnowledgeSource } from './adminApi'

export type SourceAction = 'details' | 'original' | 'metadata' | 'replace' | 'refresh' | 'status' | 'delete'

export function SourceActions({ source, busy, onAction }: {
  source: KnowledgeSource; busy: boolean; onAction: (action: SourceAction, source: KnowledgeSource) => void
}) {
  const id = useId()
  const menu = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const [position, setPosition] = useState({ top: 0, left: 0 })
  const [expanded, setExpanded] = useState(false)
  useEffect(() => {
    const close = (event: Event) => {
      if (!(event.target instanceof Node) || !menu.current?.contains(event.target)) menu.current?.hidePopover()
    }
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    return () => { window.removeEventListener('scroll', close, true); window.removeEventListener('resize', close) }
  }, [])
  const items: [SourceAction, string][] = [
    ['details', 'Xem chi tiết'],
  ]
  if (source.source_type === 'url') items.push(['original', 'Mở URL gốc'])
  items.push(
    ['metadata', 'Sửa thông tin'], [source.source_type === 'file' ? 'replace' : 'refresh', source.source_type === 'file' ? 'Thay file' : 'Cập nhật URL'],
    ['status', source.is_active ? 'Tắt nguồn' : 'Bật nguồn'], ['delete', 'Xóa nguồn'],
  )
  return <>
    <button ref={trigger} type="button" className="admin-more-button" aria-label={`Thao tác với ${source.filename}`} aria-haspopup="menu" aria-expanded={expanded} popoverTarget={id} disabled={busy}
      onClick={event => {
        event.preventDefault()
        if (menu.current!.matches(':popover-open')) { menu.current!.hidePopover(); return }
        menu.current!.showPopover()
        const rect = trigger.current!.getBoundingClientRect()
        const height = menu.current!.getBoundingClientRect().height
        setPosition({ left: Math.max(12, Math.min(rect.right - 224, window.innerWidth - 236)), top: rect.bottom + height + 12 > window.innerHeight ? Math.max(12, rect.top - height - 5) : rect.bottom + 5 })
      }} onKeyDown={event => {
        if (event.key === 'ArrowDown') { event.preventDefault(); trigger.current?.click(); requestAnimationFrame(() => menu.current?.querySelector<HTMLButtonElement>('button')?.focus()) }
      }}>⋯</button>
    <div ref={menu} id={id} popover="auto" role="menu" aria-label={`Thao tác với ${source.filename}`} className="admin-source-menu" style={position}
      onToggle={event => setExpanded(event.newState === 'open')}
      onKeyDown={event => {
        if (event.key === 'Escape') { event.preventDefault(); menu.current?.hidePopover(); trigger.current?.focus(); return }
        const buttons = Array.from(menu.current!.querySelectorAll<HTMLButtonElement>('button'))
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
        if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
          event.preventDefault()
          const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowUp' ? -1 : 1) + buttons.length) % buttons.length
          buttons[next].focus()
        }
      }}>
      {items.map(([action, label]) => <button key={action} type="button" role="menuitem" className={action === 'delete' ? 'admin-menu-danger' : undefined} onClick={() => {
        menu.current?.hidePopover(); trigger.current?.focus(); onAction(action, source)
      }}>{label}</button>)}
    </div>
  </>
}

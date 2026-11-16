import { useEffect, useRef } from 'react'
import { gsap } from 'gsap'

export function SourceSearch({ value, disabled, onChange }: { value: string; disabled: boolean; onChange: (value: string) => void }) {
  const root = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const hasQuery = Boolean(value)

  useEffect(() => {
    if (!hasQuery) return
    const mm = gsap.matchMedia()
    let entered = false
    mm.add({ all: 'all', reduceMotion: '(prefers-reduced-motion: reduce)' }, context => {
      if (entered) return
      entered = true
      if (context.conditions?.reduceMotion) return
      gsap.fromTo('.admin-source-search__clear', { opacity: 0.4, x: 3 }, {
        opacity: 1, x: 0, duration: 0.18, ease: 'power1.out', clearProps: 'transform,opacity',
      })
    }, root)
    return () => mm.revert()
  }, [hasQuery])

  return <div ref={root} className="admin-source-search">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4.5 4.5" /></svg>
    <label className="visually-hidden" htmlFor="admin-source-search">Tìm theo tên file</label>
    <input ref={input} id="admin-source-search" type="search" value={value} maxLength={255} disabled={disabled} placeholder="Tìm theo tên file…" autoComplete="off" onChange={event => onChange(event.target.value)} />
    <button className="admin-source-search__clear" type="button" aria-label="Xóa từ khóa tìm kiếm" title="Xóa từ khóa tìm kiếm" disabled={disabled || !hasQuery} onClick={() => { onChange(''); input.current?.focus() }}>×</button>
  </div>
}

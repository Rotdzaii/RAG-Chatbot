import { useEffect, useRef, useState } from 'react'
import { Link, NavLink } from 'react-router'
import { gsap } from 'gsap'
import { useAuth } from '../auth/useAuth'
import { useAdminAccess } from '../auth/useAdminAccess'
import { AccountControl } from '../auth/AccountControl'
import vluLogo from '../assets/vlu-logo.svg'
import { SourceManager } from './SourceManager'
import { AdminStatisticsPage } from './AdminStatistics'
import './admin.css'

type AdminSection = 'overview' | 'sources'

export function AdminPage({ section }: { section: AdminSection }) {
  const { session } = useAuth()
  const token = session?.access_token ?? ''
  const { handleFailure } = useAdminAccess()
  return <AdminWorkspace key={token} section={section} token={token} onFailure={handleFailure} />
}

function AdminNavigation({ onNavigate }: { onNavigate?: () => void }) {
  return <nav aria-label="Điều hướng quản trị">
    <NavLink end to="/admin" onClick={onNavigate}><span aria-hidden="true">▥</span>Tổng quan</NavLink>
    <NavLink to="/admin/sources" onClick={onNavigate}><span aria-hidden="true">▤</span>Quản lý tài liệu</NavLink>
  </nav>
}

function AdminWorkspace({ section, token, onFailure }: { section: AdminSection; token: string; onFailure: (error: unknown) => void }) {
  const panel = useRef<HTMLElement>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const mobileMenu = useRef<HTMLDialogElement>(null)
  const menuTrigger = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!menuOpen) return
    const dialog = mobileMenu.current!
    const previousTrigger = menuTrigger.current
    dialog.showModal()
    const viewport = window.matchMedia('(min-width: 761px)')
    const closeOnDesktop = () => { if (viewport.matches) setMenuOpen(false) }
    viewport.addEventListener('change', closeOnDesktop)
    return () => { dialog.close(); viewport.removeEventListener('change', closeOnDesktop); previousTrigger?.focus() }
  }, [menuOpen])
  useEffect(() => {
    const mm = gsap.matchMedia()
    mm.add('(prefers-reduced-motion: no-preference)', () => {
      gsap.fromTo(panel.current, { autoAlpha: 0.7, x: 5 }, { autoAlpha: 1, x: 0, duration: 0.2, ease: 'power1.out', clearProps: 'transform,opacity,visibility' })
    })
    return () => mm.revert()
  }, [])
  return <div className="admin-shell">
    <a className="admin-skip-link" href="#admin-main">Đến nội dung chính</a>
    <aside className="admin-sidebar admin-sidebar--desktop">
      <Link className="admin-brand" to="/" aria-label="Đại học Văn Lang, trang chủ"><img src={vluLogo} width="154" alt="Đại học Văn Lang" /></Link>
      <p className="admin-sidebar-title">Quản trị tri thức</p>
      <AdminNavigation />
      <div className="admin-sidebar-footer"><AccountControl /></div>
    </aside>
    <div className="admin-main-wrap">
      <header className="admin-topbar">
        <button ref={menuTrigger} className="admin-more-button admin-mobile-menu" aria-label="Mở điều hướng" aria-haspopup="dialog" aria-expanded={menuOpen} onClick={() => setMenuOpen(true)}>☰</button>
        <nav aria-label="Vị trí hiện tại">Quản trị / <strong aria-current="page">{section === 'overview' ? 'Tổng quan' : 'Quản lý tài liệu'}</strong></nav>
        <span className="admin-topbar-brand">VLU · Quản trị</span>
      </header>
      <main ref={panel} id="admin-main" tabIndex={-1} className="admin-main">
        {section === 'overview'
          ? <AdminStatisticsPage token={token} onFailure={onFailure} />
          : <SourceManager token={token} onFailure={onFailure} />}
      </main>
    </div>
    {menuOpen && <dialog ref={mobileMenu} className="admin-nav-dialog" aria-label="Điều hướng quản trị" onCancel={event => { event.preventDefault(); setMenuOpen(false) }} onClick={event => { if (event.target === event.currentTarget) setMenuOpen(false) }}>
      <div className="admin-sidebar"><div className="admin-nav-header"><img src={vluLogo} width="145" alt="Đại học Văn Lang" /><button className="admin-more-button" aria-label="Đóng điều hướng" onClick={() => setMenuOpen(false)}>×</button></div><p className="admin-sidebar-title">Quản trị tri thức</p><AdminNavigation onNavigate={() => setMenuOpen(false)} /><div className="admin-sidebar-footer"><AccountControl /></div></div>
    </dialog>}
  </div>
}

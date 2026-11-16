import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { gsap } from 'gsap'
import vluLogo from '../assets/vlu-logo.svg'
import { GoogleSignInButton } from '../auth/GoogleSignInButton'
import { storePendingQuestion } from '../chat/pendingQuestion'
import './HomeLoginDialog.css'

export function HomeLoginDialog({ question, onClose }: { question: string; onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const navigate = useNavigate()
  const [error, setError] = useState('')

  useEffect(() => {
    const dialog = dialogRef.current!
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    dialog.showModal()
    dialog.querySelector<HTMLButtonElement>('.home-login-dialog__close')?.focus()
    const mm = gsap.matchMedia()
    let entered = false
    mm.add({ all: 'all', reduceMotion: '(prefers-reduced-motion: reduce)' }, context => {
      if (entered) return
      entered = true
      if (context.conditions?.reduceMotion) return
      gsap.fromTo(dialog, { opacity: 0, y: 6 }, {
        opacity: 1, y: 0, duration: 0.19, ease: 'power1.out', clearProps: 'transform,opacity',
      })
    })
    return () => { mm.revert(); dialog.close(); if (previous?.isConnected) previous.focus({ preventScroll: true }) }
  }, [])

  function saveDraft() {
    if (!storePendingQuestion(question.trim())) {
      setError('Không thể lưu câu hỏi trong phiên này. Vui lòng thử lại.')
      return false
    }
    setError('')
    return true
  }

  return <dialog ref={dialogRef} className="home-login-dialog" aria-labelledby="home-login-title" aria-describedby="home-login-description"
    onKeyDown={event => {
      if (event.key !== 'Tab') return
      const buttons = event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')
      const first = buttons[0]
      const last = buttons[buttons.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }}
    onCancel={event => { event.preventDefault(); onClose() }}>
    <button type="button" className="home-login-dialog__close" aria-label="Đóng hộp đăng nhập" onClick={onClose}>×</button>
    <img className="home-login-dialog__logo" src={vluLogo} alt="Đại học Văn Lang" width="144" height="44" />
    <h2 id="home-login-title">Đăng nhập hoặc đăng ký</h2>
    <p id="home-login-description">Đăng nhập để gửi câu hỏi và lưu lịch sử trò chuyện.</p>
    <div className="home-login-dialog__actions">
      <GoogleSignInButton beforeSignIn={saveDraft} />
      <button type="button" className="home-login-dialog__email" onClick={() => {
        if (saveDraft()) navigate('/login', { state: { from: '/chat' } })
      }}>Tiếp tục bằng email</button>
    </div>
    {error && <p className="home-question__error" role="alert">{error}</p>}
  </dialog>
}

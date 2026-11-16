import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { gsap } from 'gsap'
import { HeroQuestionForm } from './HeroQuestionForm'
import { HomeHeader } from './HomeHeader'
import { HomeLoginDialog } from './HomeLoginDialog'
import { useAuth } from '../auth/useAuth'
import { readPendingQuestion } from '../chat/pendingQuestion'
import { hasHandledLoginPrompt, markLoginPromptHandled } from './loginPromptSession'
import '../App.css'
import './HomePage.css'

export function HomePage() {
  const pageRef = useRef<HTMLDivElement>(null)
  const { user, isLoading } = useAuth()
  const [question, setQuestion] = useState(readPendingQuestion)
  const [loginOpen, setLoginOpen] = useState(false)
  const autoOpenTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const hasDraft = Boolean(question)

  function skipAutoOpen() {
    markLoginPromptHandled()
    clearTimeout(autoOpenTimer.current)
  }

  function openLogin() {
    skipAutoOpen()
    setLoginOpen(true)
  }

  useEffect(() => {
    if (isLoading || user || hasHandledLoginPrompt()) return
    if (hasDraft) { markLoginPromptHandled(); return }
    autoOpenTimer.current = setTimeout(() => {
      markLoginPromptHandled()
      setLoginOpen(true)
    }, 750)
    return () => clearTimeout(autoOpenTimer.current)
  }, [user, isLoading, hasDraft])

  useLayoutEffect(() => {
    const mm = gsap.matchMedia()
    let entered = false
    mm.add({ all: 'all', reduceMotion: '(prefers-reduced-motion: reduce)' }, (context) => {
      // A preference change may end the reveal, but must never replay it.
      if (entered) return
      entered = true
      if (context.conditions?.reduceMotion) return
      gsap.fromTo('.welcome, .suggested-questions', { opacity: 0, y: 8 }, {
        opacity: 1, y: 0, duration: 0.2, ease: 'power1.out', clearProps: 'transform,opacity',
      })
    }, pageRef)
    return () => mm.revert()
  }, [])

  return (
    <div ref={pageRef} className="home-page" lang="vi">
      <HomeHeader onLogin={openLogin} />
      <main className="home-chat" aria-labelledby="home-heading">
        <div className="home-chat__content">
          <section className="welcome">
            <h1 id="home-heading">Bạn cần tìm thông tin gì tại Văn Lang?</h1>
            <p>Đặt câu hỏi về chương trình đào tạo và thông tin học vụ.</p>
          </section>
          <HeroQuestionForm question={question} onQuestionChange={value => {
            skipAutoOpen()
            setQuestion(value)
          }} onLogin={openLogin} />
        </div>
      </main>
      {loginOpen && !user && <HomeLoginDialog question={question} onClose={() => setLoginOpen(false)} />}
    </div>
  )
}

import { useEffect, useState } from 'react'
import type { FocusEvent } from 'react'
import campusGate from '../assets/images/DTTGate.avif'
import studentBanner from '../assets/images/Bannervlu.avif'

const slides = [
  {
    src: campusGate,
    alt: 'Cổng và khuôn viên Đại học Văn Lang',
    className: 'auth-carousel__image--gate',
    label: 'Khuôn viên Đại học Văn Lang',
  },
  {
    src: studentBanner,
    alt: 'Nhóm sinh viên tại Đại học Văn Lang',
    className: 'auth-carousel__image--students',
    label: 'Sinh viên Đại học Văn Lang',
  },
] as const

export function AuthCarousel() {
  const [activeSlide, setActiveSlide] = useState(0)
  const [isHovered, setIsHovered] = useState(false)
  const [isFocusWithin, setIsFocusWithin] = useState(false)
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false)
  const isPaused = isHovered || isFocusWithin

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    const updatePreference = () => setPrefersReducedMotion(mediaQuery.matches)

    updatePreference()
    mediaQuery.addEventListener('change', updatePreference)
    return () => mediaQuery.removeEventListener('change', updatePreference)
  }, [])

  useEffect(() => {
    if (isPaused || prefersReducedMotion) return

    const interval = window.setInterval(() => {
      setActiveSlide((current) => (current + 1) % slides.length)
    }, 8000)

    return () => window.clearInterval(interval)
  }, [isPaused, prefersReducedMotion])

  function handleBlur(event: FocusEvent<HTMLElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setIsFocusWithin(false)
    }
  }

  function showPrevious() {
    setActiveSlide((current) => (current - 1 + slides.length) % slides.length)
  }

  function showNext() {
    setActiveSlide((current) => (current + 1) % slides.length)
  }

  return (
    <aside
      className="auth-carousel"
      role="region"
      aria-roledescription="băng chuyền"
      aria-label="Hình ảnh Đại học Văn Lang"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onFocusCapture={() => setIsFocusWithin(true)}
      onBlurCapture={handleBlur}
    >
      <div className="auth-carousel__slides">
        {slides.map((slide, index) => {
          const isActive = index === activeSlide

          return (
            <div
              className={`auth-carousel__slide${isActive ? ' auth-carousel__slide--active' : ''}`}
              role="group"
              aria-roledescription="trang"
              aria-label={`${index + 1} / ${slides.length}: ${slide.label}`}
              aria-hidden={!isActive}
              key={slide.src}
            >
              <img className={slide.className} src={slide.src} alt={slide.alt} />
            </div>
          )
        })}
      </div>

      <div className="auth-carousel__controls">
        <button type="button" className="carousel-arrow" aria-label="Ảnh trước" onClick={showPrevious}>
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
            <path d="m12 5-5 5 5 5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>

        <div className="carousel-indicators" aria-label="Chọn ảnh">
          {slides.map((slide, index) => (
            <button
              type="button"
              className={index === activeSlide ? 'carousel-indicator carousel-indicator--active' : 'carousel-indicator'}
              aria-label={`Chuyển đến ảnh ${index + 1}: ${slide.label}`}
              aria-current={index === activeSlide ? 'true' : undefined}
              onClick={() => setActiveSlide(index)}
              key={slide.src}
            />
          ))}
        </div>

        <button type="button" className="carousel-arrow" aria-label="Ảnh tiếp theo" onClick={showNext}>
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
            <path d="m8 5 5 5-5 5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>
    </aside>
  )
}

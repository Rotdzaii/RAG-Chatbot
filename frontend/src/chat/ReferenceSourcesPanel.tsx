import { useEffect, useMemo, useRef, useState } from 'react'
import type { QuestionSource } from '../api'
import type { Conversation } from './types'
import { groupCitedSources } from './citedSources'

type ReferenceSourcesPanelProps = {
  conversation: Conversation
  isOpen: boolean
  onClose: () => void
}

type WebsiteReference = {
  url: string
  hostname: string
  displayUrl: string
}

function toWebsiteReference(source: QuestionSource): WebsiteReference | null {
  const candidate = source.filename.trim()
  if (!/^https?:\/\//i.test(candidate)) return null

  try {
    const parsedUrl = new URL(candidate)
    if (parsedUrl.protocol !== 'http:' && parsedUrl.protocol !== 'https:') return null

    parsedUrl.hash = ''
    parsedUrl.searchParams.sort()
    if (parsedUrl.pathname.length > 1) {
      parsedUrl.pathname = parsedUrl.pathname.replace(/\/+$/, '')
    }

    const normalizedUrl = parsedUrl.toString()
    return {
      url: normalizedUrl,
      hostname: parsedUrl.hostname.replace(/^www\./i, ''),
      displayUrl: `${parsedUrl.hostname}${parsedUrl.pathname === '/' ? '' : parsedUrl.pathname}${parsedUrl.search}`,
    }
  } catch {
    return null
  }
}

function collectWebsiteReferences(conversation: Conversation): WebsiteReference[] {
  const references = new Map<string, WebsiteReference>()

  for (const turn of conversation.turns) {
    if (turn.status !== 'complete') continue

    for (const group of groupCitedSources(turn.response.answer, turn.response.sources)) {
      for (const source of group.sources) {
        const reference = toWebsiteReference(source)
        if (reference && !references.has(reference.url)) {
          references.set(reference.url, reference)
        }
      }
    }
  }

  return [...references.values()]
}

export function ReferenceSourcesPanel({ conversation, isOpen, onClose }: ReferenceSourcesPanelProps) {
  const panel = useRef<HTMLElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const [isMobileDrawer, setIsMobileDrawer] = useState(() => window.matchMedia('(max-width: 900px)').matches)
  const references = useMemo(() => collectWebsiteReferences(conversation), [conversation])

  useEffect(() => {
    const mobileMedia = window.matchMedia('(max-width: 900px)')
    const handleBreakpointChange = (event: MediaQueryListEvent) => setIsMobileDrawer(event.matches)

    mobileMedia.addEventListener('change', handleBreakpointChange)
    return () => mobileMedia.removeEventListener('change', handleBreakpointChange)
  }, [])

  useEffect(() => {
    if (!isOpen) return

    const focusFrame = isMobileDrawer
      ? window.requestAnimationFrame(() => closeButton.current?.focus())
      : undefined

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }

      if (!isMobileDrawer || event.key !== 'Tab') return
      const focusableElements = panel.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), a[href]',
      )
      if (!focusableElements?.length) return

      const firstElement = focusableElements[0]
      const lastElement = focusableElements[focusableElements.length - 1]
      if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault()
        lastElement.focus()
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault()
        firstElement.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      if (focusFrame !== undefined) window.cancelAnimationFrame(focusFrame)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isMobileDrawer, isOpen, onClose])

  if (!isOpen) return null

  return (
    <>
      <button
        className="reference-sources-backdrop"
        type="button"
        tabIndex={-1}
        aria-label="Đóng nguồn tham khảo"
        onClick={onClose}
      />
      <aside
        ref={panel}
        className="reference-sources-panel"
        id="reference-sources-panel"
        role={isMobileDrawer ? 'dialog' : undefined}
        aria-modal={isMobileDrawer ? 'true' : undefined}
        aria-labelledby="reference-sources-heading"
      >
        <header className="reference-sources-panel__header">
          <h2 id="reference-sources-heading">Nguồn tham khảo</h2>
          <button
            ref={closeButton}
            className="reference-sources-panel__close"
            type="button"
            aria-label="Đóng nguồn tham khảo"
            onClick={onClose}
          >
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
              <path d="m5 5 10 10M15 5 5 15" strokeLinecap="round" />
            </svg>
          </button>
        </header>

        <div className="reference-sources-panel__body">
          {references.length === 0 ? (
            <p className="reference-sources-panel__empty">
              Chưa có nguồn tham khảo website trong cuộc trò chuyện này.
            </p>
          ) : (
            <ol className="reference-sources-list">
              {references.map((reference, index) => (
                <li key={reference.url}>
                  <a href={reference.url} target="_blank" rel="noopener noreferrer">
                    <span className="reference-source__number" aria-hidden="true">{index + 1}</span>
                    <span className="reference-source__content">
                      <strong>{reference.hostname}</strong>
                      <span>{reference.displayUrl}</span>
                    </span>
                    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                      <path d="M8 5h7v7M15 5l-8.5 8.5" strokeLinecap="round" strokeLinejoin="round" />
                      <path d="M13 11.5V15H5V7h3.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </a>
                </li>
              ))}
            </ol>
          )}
        </div>
      </aside>
    </>
  )
}

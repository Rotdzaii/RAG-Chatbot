import { useEffect, useMemo, useRef, useState } from 'react'
import type { QuestionSource } from '../api'
import type { Conversation } from './types'
import { groupCitedSources, toWebsiteReference } from './citedSources'
import { useCitationFile } from './useCitationFile'

type ReferenceSourcesPanelProps = {
  conversation: Conversation
  isOpen: boolean
  onClose: () => void
  accessToken: string | undefined
}

function collectWebsiteReferences(conversation: Conversation) {
  const references = new Map<string, NonNullable<ReturnType<typeof toWebsiteReference>>>()

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

function collectFileReferences(conversation: Conversation): QuestionSource[] {
  const references = new Map<string, QuestionSource>()
  for (const turn of conversation.turns) {
    if (turn.status !== 'complete') continue
    for (const group of groupCitedSources(turn.response.answer, turn.response.sources)) {
      for (const source of group.sources) {
        if (toWebsiteReference(source)) continue
        const key = `${source.source_file_version_id ?? 'legacy'}:${source.chunk_id}:${source.page_start ?? ''}`
        if (!references.has(key)) references.set(key, source)
      }
    }
  }
  return [...references.values()]
}

export function ReferenceSourcesPanel({ conversation, isOpen, onClose, accessToken }: ReferenceSourcesPanelProps) {
  const panel = useRef<HTMLElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const [isMobileDrawer, setIsMobileDrawer] = useState(() => window.matchMedia('(max-width: 900px)').matches)
  const references = useMemo(() => collectWebsiteReferences(conversation), [conversation])
  const fileReferences = useMemo(() => collectFileReferences(conversation), [conversation])
  const { openFile, feedback } = useCitationFile(accessToken)

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
          {feedback && <p role={feedback.kind === 'error' ? 'alert' : 'status'}>{feedback.message}</p>}
          {references.length === 0 && fileReferences.length === 0 ? (
            <p className="reference-sources-panel__empty">
              Chưa có nguồn tham khảo trong cuộc trò chuyện này.
            </p>
          ) : (
            <>
            {fileReferences.length > 0 && (
              <ol className="reference-sources-list">
                {fileReferences.map((source, index) => (
                  <li key={`${source.source_file_version_id ?? 'legacy'}:${source.chunk_id}:${source.page_start ?? ''}`}>
                    {source.source_file_version_id ? (
                      <button type="button" onClick={() => void openFile(source, source.mime_type === 'text/plain' || (source.mime_type == null && /\.txt$/i.test(source.filename)))}>
                        <span className="reference-source__number" aria-hidden="true">{index + 1}</span>
                        <span className="reference-source__content">
                          <strong>{source.filename}</strong>
                          <span>{source.page_start ? `Trang ${source.page_start}${source.page_end && source.page_end !== source.page_start ? `–${source.page_end}` : ''}` : `Đoạn ${source.chunk_index + 1}`} · {source.mime_type === 'text/plain' ? 'Tải TXT' : 'Mở file gốc'}</span>
                        </span>
                      </button>
                    ) : (
                      <span className="reference-source__content">
                        <strong>{source.filename}</strong>
                        <span>Chưa lưu file gốc cho trích dẫn này.</span>
                      </span>
                    )}
                  </li>
                ))}
              </ol>
            )}
            {references.length > 0 && (
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
            </>
          )}
        </div>
      </aside>
    </>
  )
}

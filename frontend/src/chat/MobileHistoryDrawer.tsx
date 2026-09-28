import { useEffect, useRef } from 'react'
import vluLogo from '../assets/vlu-logo.svg'
import { AccountControl } from '../auth/AccountControl'
import { ConversationList } from './ConversationList'
import type { Conversation } from './types'

type MobileHistoryDrawerProps = {
  isOpen: boolean
  conversations: Conversation[]
  activeConversationId: string | null
  pendingConversationId: string | null
  isHistoryLoading: boolean
  historyError?: string
  onClose: () => void
  onCreate: () => void
  onRetryHistory: () => void
  onSelect: (conversationId: string) => void
}

export function MobileHistoryDrawer({
  isOpen,
  conversations,
  activeConversationId,
  pendingConversationId,
  isHistoryLoading,
  historyError,
  onClose,
  onCreate,
  onRetryHistory,
  onSelect,
}: MobileHistoryDrawerProps) {
  const closeButton = useRef<HTMLButtonElement>(null)
  const drawer = useRef<HTMLElement>(null)

  useEffect(() => {
    if (!isOpen) return

    const desktopViewport = window.matchMedia('(min-width: 901px)')
    if (desktopViewport.matches) {
      onClose()
      return
    }

    const previousOverflow = document.body.style.overflow
    const focusFrame = window.requestAnimationFrame(() => closeButton.current?.focus())
    const handleViewportChange = (event: MediaQueryListEvent) => {
      if (event.matches) onClose()
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
        return
      }

      if (event.key !== 'Tab') return
      const focusableElements = drawer.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled), [href], [tabindex]:not([tabindex="-1"])',
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

    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', handleKeyDown)
    desktopViewport.addEventListener('change', handleViewportChange)

    return () => {
      window.cancelAnimationFrame(focusFrame)
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', handleKeyDown)
      desktopViewport.removeEventListener('change', handleViewportChange)
    }
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    <div className="history-drawer-layer">
      <button className="history-drawer__overlay" type="button" tabIndex={-1} aria-label="Đóng lịch sử trò chuyện" onClick={onClose} />
      <aside
        ref={drawer}
        id="mobile-history-drawer"
        className="history-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="history-drawer-heading"
      >
        <div className="history-drawer__header">
          <div>
            <img className="history-drawer__logo" src={vluLogo} alt="Đại học Văn Lang" width={116} height={36} />
            <h2 className="history-drawer__title" id="history-drawer-heading">Lịch sử trò chuyện</h2>
          </div>
          <button ref={closeButton} className="history-drawer__close" type="button" aria-label="Đóng lịch sử trò chuyện" onClick={onClose}>
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
              <path d="m5 5 10 10M15 5 5 15" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <button className="new-conversation-button" type="button" onClick={() => {
          onCreate()
          onClose()
        }}>
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
            <path d="M10 4v12M4 10h12" strokeLinecap="round" />
          </svg>
          <span>Cuộc trò chuyện mới</span>
        </button>

        <ConversationList
          conversations={conversations}
          activeConversationId={activeConversationId}
          pendingConversationId={pendingConversationId}
          isLoading={isHistoryLoading}
          loadError={historyError}
          onRetryLoad={onRetryHistory}
          onSelect={(conversationId) => {
            onSelect(conversationId)
            onClose()
          }}
        />

        <div className="history-drawer__footer">
          <AccountControl />
        </div>
      </aside>
    </div>
  )
}

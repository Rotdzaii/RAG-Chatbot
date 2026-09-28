import { useCallback, useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { ShareConversationModal } from './ShareConversationModal'
import type { Conversation } from './types'

type CurrentConversationToolbarProps = {
  conversation: Conversation
  isRequestPending: boolean
  isReferencePanelOpen: boolean
  referencePanelTriggerRef: RefObject<HTMLButtonElement | null>
  onToggleReferencePanel: () => void
  onTogglePin: (conversationId: string) => void
  onDelete: (conversationId: string) => void
}

type DeleteConversationDialogProps = {
  isOpen: boolean
  conversationTitle: string
  isRequestPending: boolean
  onClose: () => void
  onConfirm: () => void
}

function DeleteConversationDialog({
  isOpen,
  conversationTitle,
  isRequestPending,
  onClose,
  onConfirm,
}: DeleteConversationDialogProps) {
  const dialog = useRef<HTMLDivElement>(null)
  const cancelButton = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!isOpen) return

    const focusFrame = window.requestAnimationFrame(() => cancelButton.current?.focus())
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
        return
      }

      if (event.key !== 'Tab') return
      const focusableElements = dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled)')
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
      window.cancelAnimationFrame(focusFrame)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    <div className="chat-dialog-layer">
      <button className="chat-dialog__overlay" type="button" tabIndex={-1} aria-label="Hủy xóa đoạn chat" onClick={onClose} />
      <div
        ref={dialog}
        className="chat-dialog chat-dialog--compact"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="delete-dialog-heading"
        aria-describedby="delete-dialog-description"
      >
        <h2 id="delete-dialog-heading">Xóa đoạn chat?</h2>
        <p className="delete-dialog__title" title={conversationTitle}>{conversationTitle}</p>
        <p id="delete-dialog-description">
          Thao tác này sẽ xóa cuộc trò chuyện khỏi phiên hiện tại.
        </p>
        {isRequestPending && (
          <p className="delete-dialog__warning" role="status">Hãy chờ câu trả lời hiện tại hoàn tất trước khi xóa.</p>
        )}
        <div className="chat-dialog__actions">
          <button ref={cancelButton} type="button" onClick={onClose}>Hủy</button>
          <button className="chat-dialog__danger-action" type="button" disabled={isRequestPending} onClick={onConfirm}>Xóa đoạn chat</button>
        </div>
      </div>
    </div>
  )
}

export function CurrentConversationToolbar({
  conversation,
  isRequestPending,
  isReferencePanelOpen,
  referencePanelTriggerRef,
  onToggleReferencePanel,
  onTogglePin,
  onDelete,
}: CurrentConversationToolbarProps) {
  const [isMenuOpen, setIsMenuOpen] = useState(false)
  const [isShareOpen, setIsShareOpen] = useState(false)
  const [isDeleteOpen, setIsDeleteOpen] = useState(false)
  const toolbar = useRef<HTMLDivElement>(null)
  const shareTrigger = useRef<HTMLButtonElement>(null)
  const menuTrigger = useRef<HTMLButtonElement>(null)
  const previousConversationId = useRef(conversation.id)
  const hasShareableContent = conversation.turns.length > 0 || Boolean(conversation.draft.trim())

  const closeMenu = useCallback((restoreFocus = true) => {
    setIsMenuOpen(false)
    if (restoreFocus) window.requestAnimationFrame(() => menuTrigger.current?.focus())
  }, [])

  const closeShare = useCallback(() => {
    setIsShareOpen(false)
    window.requestAnimationFrame(() => shareTrigger.current?.focus())
  }, [])

  const closeDelete = useCallback(() => {
    setIsDeleteOpen(false)
    window.requestAnimationFrame(() => menuTrigger.current?.focus())
  }, [])

  useEffect(() => {
    if (!isMenuOpen) return

    const handlePointerDown = (event: PointerEvent) => {
      if (!toolbar.current?.contains(event.target as Node)) closeMenu()
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeMenu()
    }

    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [closeMenu, isMenuOpen])

  useEffect(() => {
    if (previousConversationId.current === conversation.id) return

    const shouldRestoreMenuFocus = isMenuOpen || isDeleteOpen
    previousConversationId.current = conversation.id
    setIsMenuOpen(false)
    setIsDeleteOpen(false)
    setIsShareOpen(false)
    if (shouldRestoreMenuFocus) {
      window.requestAnimationFrame(() => menuTrigger.current?.focus())
    }
  }, [conversation.id, isDeleteOpen, isMenuOpen])

  function handleTogglePin() {
    onTogglePin(conversation.id)
    closeMenu()
  }

  function handleRequestDelete() {
    if (isRequestPending) return
    closeMenu(false)
    setIsDeleteOpen(true)
  }

  function handleConfirmDelete() {
    if (isRequestPending) return
    setIsDeleteOpen(false)
    onDelete(conversation.id)
    window.requestAnimationFrame(() => menuTrigger.current?.focus())
  }

  function handleToggleReferencePanel() {
    closeMenu(false)
    onToggleReferencePanel()
  }

  return (
    <>
      <div className="conversation-toolbar" ref={toolbar} aria-label="Thao tác cuộc trò chuyện hiện tại">
        <button
          ref={shareTrigger}
          className="conversation-toolbar__share"
          type="button"
          disabled={!hasShareableContent}
          title={hasShareableContent ? 'Chia sẻ cuộc trò chuyện' : 'Chưa có nội dung để chia sẻ'}
          onClick={() => setIsShareOpen(true)}
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
            <path d="M10 12.2V3.5M6.8 6.7 10 3.5l3.2 3.2" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M4.2 10.4v4.1c0 1.1.9 2 2 2h7.6c1.1 0 2-.9 2-2v-4.1" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span>Chia sẻ</span>
        </button>

        <button
          ref={menuTrigger}
          className="conversation-toolbar__menu-trigger"
          type="button"
          aria-label="Mở menu cuộc trò chuyện"
          aria-haspopup="menu"
          aria-expanded={isMenuOpen}
          onClick={() => setIsMenuOpen((open) => !open)}
        >
          <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
            <circle cx="4" cy="10" r="1.4" />
            <circle cx="10" cy="10" r="1.4" />
            <circle cx="16" cy="10" r="1.4" />
          </svg>
        </button>

        <button
          ref={referencePanelTriggerRef}
          className={`conversation-toolbar__sources${isReferencePanelOpen ? ' conversation-toolbar__sources--active' : ''}`}
          type="button"
          title="Xem nguồn tham khảo"
          aria-label="Xem nguồn tham khảo"
          aria-expanded={isReferencePanelOpen}
          aria-controls="reference-sources-panel"
          onClick={handleToggleReferencePanel}
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <circle cx="5" cy="6" r="2" />
            <path d="M10 6h9" />
            <circle cx="5" cy="12" r="2" />
            <path d="M10 12h9" />
            <circle cx="5" cy="18" r="2" />
            <path d="M10 18h9" />
          </svg>
        </button>

        {isMenuOpen && (
          <div className="conversation-action-menu" role="menu" aria-label="Menu cuộc trò chuyện">
            <button type="button" role="menuitem" onClick={handleTogglePin}>
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                <path d="m6.4 3.5 7.2 2-1.9 2.7 1 2.6-2.8.8L7.5 17l-.6-5.2-2.3-1.7 2.9-1.4-1.1-5.2Z" strokeLinejoin="round" />
              </svg>
              {conversation.isPinned ? 'Bỏ ghim' : 'Ghim đoạn chat'}
            </button>
            <button
              className="conversation-action-menu__danger"
              type="button"
              role="menuitem"
              disabled={isRequestPending}
              title={isRequestPending ? 'Hãy chờ câu trả lời hoàn tất trước khi xóa' : undefined}
              onClick={handleRequestDelete}
            >
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                <path d="M4.5 6h11M8 3.8h4M6.2 6l.5 10h6.6l.5-10M8.3 8.5v5M11.7 8.5v5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Xóa đoạn chat
            </button>
          </div>
        )}
      </div>

      {isShareOpen && (
        <ShareConversationModal isOpen conversation={conversation} onClose={closeShare} />
      )}
      <DeleteConversationDialog
        isOpen={isDeleteOpen}
        conversationTitle={conversation.title}
        isRequestPending={isRequestPending}
        onClose={closeDelete}
        onConfirm={handleConfirmDelete}
      />
    </>
  )
}

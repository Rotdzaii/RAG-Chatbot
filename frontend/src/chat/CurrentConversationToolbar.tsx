import { useCallback, useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { ShareConversationModal } from './ShareConversationModal'
import type { Conversation } from './types'

type CurrentConversationToolbarProps = {
  conversation: Conversation
  isRequestPending: boolean
  isActionPending: boolean
  actionError?: string
  isReferencePanelOpen: boolean
  referencePanelTriggerRef: RefObject<HTMLButtonElement | null>
  onToggleReferencePanel: () => void
  onRename: (conversationId: string, title: string) => Promise<boolean>
  onTogglePin: (conversationId: string) => Promise<boolean>
  onDelete: (conversationId: string) => Promise<boolean>
}

type ConversationDialogProps = {
  mode: 'rename' | 'delete'
  conversationTitle: string
  isPending: boolean
  errorMessage?: string
  onClose: () => void
  onRename: (title: string) => Promise<boolean>
  onDelete: () => Promise<boolean>
}

function ConversationDialog({
  mode,
  conversationTitle,
  isPending,
  errorMessage,
  onClose,
  onRename,
  onDelete,
}: ConversationDialogProps) {
  const dialog = useRef<HTMLDivElement>(null)
  const firstControl = useRef<HTMLInputElement | HTMLButtonElement>(null)
  const [title, setTitle] = useState(conversationTitle)
  const titleIsValid = Boolean(title.trim()) && title.trim().length <= 200

  useEffect(() => {
    const focusFrame = window.requestAnimationFrame(() => firstControl.current?.focus())
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isPending) {
        onClose()
        return
      }
      if (event.key !== 'Tab') return
      const elements = dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)')
      if (!elements?.length) return
      const first = elements[0]
      const last = elements[elements.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      window.cancelAnimationFrame(focusFrame)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isPending, onClose])

  async function handleSubmit() {
    const succeeded = mode === 'rename'
      ? await onRename(title.trim())
      : await onDelete()
    if (succeeded) onClose()
  }

  const heading = mode === 'rename' ? 'Đổi tên đoạn chat' : 'Xóa đoạn chat?'
  return (
    <div className="chat-dialog-layer">
      <button className="chat-dialog__overlay" type="button" tabIndex={-1} aria-label="Đóng hộp thoại" disabled={isPending} onClick={onClose} />
      <div ref={dialog} className="chat-dialog chat-dialog--compact" role={mode === 'delete' ? 'alertdialog' : 'dialog'} aria-modal="true" aria-labelledby="conversation-dialog-heading">
        <h2 id="conversation-dialog-heading">{heading}</h2>
        {mode === 'rename' ? (
          <label className="rename-dialog__field">
            <span>Tên cuộc trò chuyện</span>
            <input
              ref={firstControl as RefObject<HTMLInputElement>}
              value={title}
              maxLength={200}
              disabled={isPending}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
        ) : (
          <>
            <p className="delete-dialog__title" title={conversationTitle}>{conversationTitle}</p>
            <p>Thao tác này sẽ xóa cuộc trò chuyện và toàn bộ tin nhắn đã lưu.</p>
          </>
        )}
        {errorMessage && <p className="delete-dialog__warning" role="alert">{errorMessage}</p>}
        <div className="chat-dialog__actions">
          <button ref={mode === 'delete' ? firstControl as RefObject<HTMLButtonElement> : undefined} type="button" disabled={isPending} onClick={onClose}>Hủy</button>
          <button
            className={mode === 'delete' ? 'chat-dialog__danger-action' : 'chat-dialog__primary-action'}
            type="button"
            disabled={isPending || (mode === 'rename' && !titleIsValid)}
            onClick={() => void handleSubmit()}
          >
            {isPending ? 'Đang lưu…' : mode === 'rename' ? 'Lưu tên' : 'Xóa đoạn chat'}
          </button>
        </div>
      </div>
    </div>
  )
}

export function CurrentConversationToolbar({
  conversation,
  isRequestPending,
  isActionPending,
  actionError,
  isReferencePanelOpen,
  referencePanelTriggerRef,
  onToggleReferencePanel,
  onRename,
  onTogglePin,
  onDelete,
}: CurrentConversationToolbarProps) {
  const [isMenuOpen, setIsMenuOpen] = useState(false)
  const [isShareOpen, setIsShareOpen] = useState(false)
  const [dialogMode, setDialogMode] = useState<'rename' | 'delete' | null>(null)
  const toolbar = useRef<HTMLDivElement>(null)
  const shareTrigger = useRef<HTMLButtonElement>(null)
  const menuTrigger = useRef<HTMLButtonElement>(null)
  const previousConversationId = useRef(conversation.id)
  const hasShareableContent = conversation.turns.length > 0 || Boolean(conversation.draft.trim())
  const canMutate = Boolean(conversation.serverId) && !isRequestPending && !isActionPending

  const closeMenu = useCallback((restoreFocus = true) => {
    setIsMenuOpen(false)
    if (restoreFocus) window.requestAnimationFrame(() => menuTrigger.current?.focus())
  }, [])

  const closeShare = useCallback(() => {
    setIsShareOpen(false)
    window.requestAnimationFrame(() => shareTrigger.current?.focus())
  }, [])

  const closeDialog = useCallback(() => {
    setDialogMode(null)
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
    previousConversationId.current = conversation.id
    setIsMenuOpen(false)
    setDialogMode(null)
    setIsShareOpen(false)
  }, [conversation.id])

  function openDialog(mode: 'rename' | 'delete') {
    if (!canMutate) return
    closeMenu(false)
    setDialogMode(mode)
  }

  function handleToggleReferencePanel() {
    closeMenu(false)
    onToggleReferencePanel()
  }

  return (
    <>
      <div className="conversation-toolbar" ref={toolbar} aria-label="Thao tác cuộc trò chuyện hiện tại">
        <button ref={shareTrigger} className="conversation-toolbar__share" type="button" disabled={!hasShareableContent} title={hasShareableContent ? 'Chia sẻ cuộc trò chuyện' : 'Chưa có nội dung để chia sẻ'} onClick={() => setIsShareOpen(true)}>
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
            <path d="M10 12.2V3.5M6.8 6.7 10 3.5l3.2 3.2" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M4.2 10.4v4.1c0 1.1.9 2 2 2h7.6c1.1 0 2-.9 2-2v-4.1" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span>Chia sẻ</span>
        </button>

        <button ref={menuTrigger} className="conversation-toolbar__menu-trigger" type="button" aria-label="Mở menu cuộc trò chuyện" aria-haspopup="menu" aria-expanded={isMenuOpen} onClick={() => setIsMenuOpen((open) => !open)}>
          <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
            <circle cx="4" cy="10" r="1.4" /><circle cx="10" cy="10" r="1.4" /><circle cx="16" cy="10" r="1.4" />
          </svg>
        </button>

        <button ref={referencePanelTriggerRef} className={`conversation-toolbar__sources${isReferencePanelOpen ? ' conversation-toolbar__sources--active' : ''}`} type="button" title="Xem nguồn tham khảo" aria-label="Xem nguồn tham khảo" aria-expanded={isReferencePanelOpen} aria-controls="reference-sources-panel" onClick={handleToggleReferencePanel}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="5" cy="6" r="2" /><path d="M10 6h9" /><circle cx="5" cy="12" r="2" /><path d="M10 12h9" /><circle cx="5" cy="18" r="2" /><path d="M10 18h9" />
          </svg>
        </button>

        {isMenuOpen && (
          <div className="conversation-action-menu" role="menu" aria-label="Menu cuộc trò chuyện">
            <button type="button" role="menuitem" disabled={!canMutate} onClick={() => openDialog('rename')}>
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m4 14.5.5-3L12.8 3.2l3 3-8.3 8.3-3 .5Z" strokeLinejoin="round" /></svg>
              Đổi tên đoạn chat
            </button>
            <button type="button" role="menuitem" disabled={!canMutate} onClick={() => { closeMenu(); void onTogglePin(conversation.id) }}>
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m6.4 3.5 7.2 2-1.9 2.7 1 2.6-2.8.8L7.5 17l-.6-5.2-2.3-1.7 2.9-1.4-1.1-5.2Z" strokeLinejoin="round" /></svg>
              {conversation.isPinned ? 'Bỏ ghim' : 'Ghim đoạn chat'}
            </button>
            <button className="conversation-action-menu__danger" type="button" role="menuitem" disabled={!canMutate} onClick={() => openDialog('delete')}>
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M4.5 6h11M8 3.8h4M6.2 6l.5 10h6.6l.5-10M8.3 8.5v5M11.7 8.5v5" strokeLinecap="round" strokeLinejoin="round" /></svg>
              Xóa đoạn chat
            </button>
          </div>
        )}
        {actionError && <p className="conversation-toolbar__error" role="alert">{actionError}</p>}
      </div>

      {isShareOpen && <ShareConversationModal isOpen conversation={conversation} onClose={closeShare} />}
      {dialogMode && (
        <ConversationDialog
          mode={dialogMode}
          conversationTitle={conversation.title}
          isPending={isActionPending}
          errorMessage={actionError}
          onClose={closeDialog}
          onRename={(title) => onRename(conversation.id, title)}
          onDelete={() => onDelete(conversation.id)}
        />
      )}
    </>
  )
}

import { useEffect, useRef, useState } from 'react'
import { sortConversations } from './conversationUtils'
import type { Conversation } from './types'

function searchableTitle(value: string) {
  return value.normalize('NFD').replace(/\p{M}/gu, '').toLocaleLowerCase('vi').replace(/đ/g, 'd').trim()
}

export function ConversationSearchDialog({ conversations, isLoading, loadError, onRetry, onClose, onSelect }: {
  conversations: Conversation[]
  isLoading: boolean
  loadError?: string
  onRetry: () => void
  onClose: () => void
  onSelect: (conversationId: string) => void
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')
  const results = sortConversations(conversations).filter(item => searchableTitle(item.title).includes(searchableTitle(query)))

  useEffect(() => {
    const dialog = dialogRef.current!
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    dialog.showModal()
    inputRef.current?.focus()
    return () => { dialog.close(); if (previous?.isConnected) previous.focus({ preventScroll: true }) }
  }, [])

  return <dialog ref={dialogRef} className="conversation-search-dialog" aria-labelledby="conversation-search-heading"
    onCancel={event => { event.preventDefault(); onClose() }}
    onKeyDown={event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); onClose(); return }
      if (event.key !== 'Tab') return
      const controls = event.currentTarget.querySelectorAll<HTMLElement>('input, button:not(:disabled)')
      const first = controls[0]
      const last = controls[controls.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }}>
    <div className="conversation-search-dialog__header">
      <h2 id="conversation-search-heading">Tìm cuộc trò chuyện</h2>
      <button type="button" className="history-drawer__close" aria-label="Đóng tìm kiếm" title="Đóng tìm kiếm" onClick={onClose}>×</button>
    </div>
    <label className="visually-hidden" htmlFor="conversation-search-input">Tìm theo tiêu đề</label>
    <input ref={inputRef} id="conversation-search-input" type="search" placeholder="Tìm theo tiêu đề…" value={query} onChange={event => setQuery(event.target.value)} autoComplete="off" />
    <div className="conversation-search-dialog__results">
      {isLoading ? <p role="status">Đang tải lịch sử…</p>
        : loadError ? <div role="alert"><p>{loadError}</p><button className="retry-button" type="button" onClick={onRetry}>Thử lại</button></div>
          : <>
            <p className="conversation-search-dialog__status" role="status">{results.length ? `${results.length} cuộc trò chuyện` : query.trim() ? 'Không tìm thấy cuộc trò chuyện phù hợp.' : 'Chưa có cuộc trò chuyện nào.'}</p>
            <ul aria-label="Kết quả tìm kiếm cuộc trò chuyện">
              {results.map(item => <li key={item.id}><button type="button" title={item.title} onClick={() => onSelect(item.id)}>{item.title}</button></li>)}
            </ul>
          </>}
    </div>
  </dialog>
}

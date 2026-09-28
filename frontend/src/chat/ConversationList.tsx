import { useId } from 'react'
import type { Conversation } from './types'
import { sortConversations } from './conversationUtils'

type ConversationListProps = {
  conversations: Conversation[]
  activeConversationId: string | null
  pendingConversationId: string | null
  isLoading: boolean
  loadError?: string
  onRetryLoad: () => void
  onSelect: (conversationId: string) => void
}

export function ConversationList({
  conversations,
  activeConversationId,
  pendingConversationId,
  isLoading,
  loadError,
  onRetryLoad,
  onSelect,
}: ConversationListProps) {
  const componentId = useId()

  const orderedConversations = sortConversations(conversations)
  const pinnedConversations = orderedConversations.filter((conversation) => conversation.isPinned)
  const recentConversations = orderedConversations.filter((conversation) => !conversation.isPinned)

  function renderGroup(groupId: string, label: string, group: Conversation[]) {
    if (group.length === 0) return null
    const headingId = `${componentId}-conversation-group-${groupId}`

    return (
      <section className="conversation-list__group" aria-labelledby={headingId}>
        <h2 className="history-section-label" id={headingId}>{label}</h2>
        <ol className="conversation-list__items">
          {group.map((conversation) => {
            const isActive = conversation.id === activeConversationId
            const isPending = conversation.id === pendingConversationId

            return (
              <li className={isActive ? 'conversation-list__item conversation-list__item--active' : 'conversation-list__item'} key={conversation.id}>
                <button
                  className="conversation-select"
                  type="button"
                  aria-current={isActive ? 'page' : undefined}
                  title={conversation.title}
                  onClick={() => onSelect(conversation.id)}
                >
                  {conversation.isPinned && (
                    <svg className="conversation-select__pin" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
                      <path d="m5.1 2.7 5.8 1.6-1.5 2.1.8 2.1-2.3.6L6 13.2 5.6 9 3.8 7.6l2.3-1.1-1-3.8Z" strokeLinejoin="round" />
                    </svg>
                  )}
                  <span className="conversation-select__title">{conversation.title}</span>
                  {isPending && <span className="conversation-select__pending" role="status" aria-label="Đang trả lời" title="Đang trả lời" />}
                </button>
              </li>
            )
          })}
        </ol>
      </section>
    )
  }

  return (
    <nav className="conversation-list" aria-label="Danh sách cuộc trò chuyện">
      {isLoading && <p className="conversation-list__status" role="status">Đang tải lịch sử…</p>}
      {loadError && (
        <div className="conversation-list__error" role="alert">
          <p>{loadError}</p>
          <button type="button" onClick={onRetryLoad}>Thử lại</button>
        </div>
      )}
      {!isLoading && !loadError && conversations.length === 0 && (
        <p className="conversation-list__empty">Chưa có cuộc trò chuyện nào.</p>
      )}
      {renderGroup('pinned', 'Đã ghim', pinnedConversations)}
      {renderGroup('recent', 'Gần đây', recentConversations)}
    </nav>
  )
}

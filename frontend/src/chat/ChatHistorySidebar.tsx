import vluLogo from '../assets/vlu-logo.svg'
import { AccountControl } from '../auth/AccountControl'
import { ConversationList } from './ConversationList'
import type { Conversation } from './types'

type ChatHistorySidebarProps = {
  conversations: Conversation[]
  activeConversationId: string | null
  pendingConversationId: string | null
  isHistoryLoading: boolean
  historyError?: string
  isCollapsed: boolean
  onToggleCollapsed: () => void
  onCreate: () => void
  onRetryHistory: () => void
  onSelect: (conversationId: string) => void
}

export function ChatHistorySidebar({
  conversations,
  activeConversationId,
  pendingConversationId,
  isHistoryLoading,
  historyError,
  isCollapsed,
  onToggleCollapsed,
  onCreate,
  onRetryHistory,
  onSelect,
}: ChatHistorySidebarProps) {
  return (
    <aside className={isCollapsed ? 'history-sidebar history-sidebar--collapsed' : 'history-sidebar'} aria-label="Lịch sử trò chuyện">
      <div className="history-sidebar__header">
        <a className="history-sidebar__brand" href="#conversation" aria-label="Đại học Văn Lang, về cuộc trò chuyện" title="Đại học Văn Lang">
          {isCollapsed ? (
            <span className="history-sidebar__brand-mark" aria-hidden="true">VLU</span>
          ) : (
            <img src={vluLogo} alt="Đại học Văn Lang" width={126} height={39} />
          )}
        </a>
        <button
          className="history-sidebar__collapse"
          type="button"
          aria-label={isCollapsed ? 'Mở rộng lịch sử trò chuyện' : 'Thu gọn lịch sử trò chuyện'}
          title={isCollapsed ? 'Mở rộng' : 'Thu gọn'}
          onClick={onToggleCollapsed}
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
            <path d={isCollapsed ? 'm8 5 5 5-5 5' : 'm12 5-5 5 5 5'} strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>

      <button
        className={isCollapsed ? 'new-conversation-button new-conversation-button--collapsed' : 'new-conversation-button'}
        type="button"
        aria-label="Cuộc trò chuyện mới"
        title={isCollapsed ? 'Cuộc trò chuyện mới' : undefined}
        onClick={onCreate}
      >
        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
          <path d="M10 4v12M4 10h12" strokeLinecap="round" />
        </svg>
        {!isCollapsed && <span>Cuộc trò chuyện mới</span>}
      </button>

      {!isCollapsed && <ConversationList
        conversations={conversations}
        activeConversationId={activeConversationId}
        pendingConversationId={pendingConversationId}
        isLoading={isHistoryLoading}
        loadError={historyError}
        onRetryLoad={onRetryHistory}
        onSelect={onSelect}
      />}

      <div className="history-sidebar__footer">
        <AccountControl />
      </div>
    </aside>
  )
}

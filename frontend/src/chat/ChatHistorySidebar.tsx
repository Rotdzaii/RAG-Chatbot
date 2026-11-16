import vluLogo from '../assets/vlu-logo.svg'
import { AccountControl } from '../auth/AccountControl'
import { ConversationList } from './ConversationList'
import { ConversationSearchButton } from './ConversationSearchButton'
import { SidebarIcon } from './SidebarIcon'
import { NewConversationIcon } from './NewConversationIcon'
import type { Conversation } from './types'

type ChatHistorySidebarProps = {
  conversations: Conversation[]
  activeConversationId: string | null
  pendingConversationId: string | null
  isHistoryLoading: boolean
  historyError?: string
  isCollapsed: boolean
  onToggleCollapsed: () => void
  onSearch: () => void
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
  onSearch,
  onCreate,
  onRetryHistory,
  onSelect,
}: ChatHistorySidebarProps) {
  return (
    <aside className={isCollapsed ? 'history-sidebar history-sidebar--collapsed' : 'history-sidebar'} aria-label="Lịch sử trò chuyện"
      onClick={event => {
        if (!isCollapsed || !(event.target instanceof Element)) return
        // Let controls handle their own clicks, including clicks on their SVGs.
        if (event.target.closest('button, a, input, select, textarea, [role="button"]')) return
        onToggleCollapsed()
      }}>
      <div className="history-sidebar__header">
        {!isCollapsed && <a className="history-sidebar__brand" href="#conversation" aria-label="Đại học Văn Lang, về cuộc trò chuyện" title="Đại học Văn Lang">
          <img src={vluLogo} alt="Đại học Văn Lang" width={126} height={39} />
        </a>}
        <button
          className={isCollapsed ? 'history-sidebar__collapse history-sidebar__collapse--brand' : 'history-sidebar__collapse'}
          type="button"
          aria-label={isCollapsed ? 'Mở sidebar' : 'Thu gọn sidebar'}
          title={isCollapsed ? 'Mở sidebar' : 'Thu gọn sidebar'}
          aria-expanded={!isCollapsed}
          onClick={onToggleCollapsed}
        >
          {isCollapsed ? <>
            <span className="history-sidebar__brand-mark" aria-hidden="true"><img src={vluLogo} alt="" /></span>
            <span className="history-sidebar__toggle-icon" aria-hidden="true"><SidebarIcon /></span>
          </> : <SidebarIcon />}
        </button>
      </div>

      <div className="history-sidebar__actions">
        <button
          className={isCollapsed ? 'new-conversation-button new-conversation-button--collapsed' : 'new-conversation-button'}
          type="button"
          aria-label="Cuộc trò chuyện mới"
          title={isCollapsed ? 'Cuộc trò chuyện mới' : undefined}
          onClick={onCreate}
        >
          <NewConversationIcon />
          {!isCollapsed && <span>Cuộc trò chuyện mới</span>}
        </button>
        <ConversationSearchButton showLabel={!isCollapsed} onClick={onSearch} />
      </div>

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

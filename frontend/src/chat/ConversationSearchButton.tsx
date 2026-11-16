export function ConversationSearchButton({ onClick, showLabel = false }: { onClick: () => void; showLabel?: boolean }) {
  return <button className={showLabel ? 'history-search-button history-search-button--labeled' : 'history-search-button'} type="button" aria-label="Tìm cuộc trò chuyện" title="Tìm cuộc trò chuyện" aria-haspopup="dialog" onClick={onClick}>
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden="true">
      <circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4.5 4.5" />
    </svg>
    {showLabel && <span>Tìm cuộc trò chuyện</span>}
  </button>
}

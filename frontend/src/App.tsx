import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiNetworkError,
  ApiRequestError,
  QuestionAuthenticationError,
  askQuestion,
  deleteConversation as deleteConversationRequest,
  getConversationMessages,
  listConversations,
  updateConversation,
} from './api'
import './App.css'
import vluLogo from './assets/vlu-logo.svg'
import { useAuth } from './auth/useAuth'
import { ChatComposer } from './chat/ChatComposer'
import { ChatHistorySidebar } from './chat/ChatHistorySidebar'
import { ChatTranscript } from './chat/ChatTranscript'
import { CurrentConversationToolbar } from './chat/CurrentConversationToolbar'
import { MobileHistoryDrawer } from './chat/MobileHistoryDrawer'
import { ReferenceSourcesPanel } from './chat/ReferenceSourcesPanel'
import { SuggestedQuestions } from './chat/SuggestedQuestions'
import {
  applyConversationMetadata,
  createConversation,
  mergeConversationList,
  createConversationTitle,
} from './chat/conversationUtils'
import { mapMessagesToTurns } from './chat/messageMapping'
import {
  consumePendingQuestion,
  finishPendingQuestionConsumption,
} from './chat/pendingQuestion'
import type {
  ChatTurn,
  Conversation,
  ConversationActionState,
  PendingRequest,
} from './chat/types'

const SESSION_EXPIRED_MESSAGE =
  'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại để tiếp tục.'
const DEFAULT_REQUEST_ERROR = 'Không thể gửi câu hỏi lúc này. Vui lòng thử lại sau.'
const HISTORY_LOAD_ERROR = 'Không thể tải lịch sử trò chuyện. Vui lòng thử lại.'

function hasValidAccessToken(session: ReturnType<typeof useAuth>['session']) {
  return Boolean(
    session?.access_token &&
      (!session.expires_at || session.expires_at * 1000 > Date.now()),
  )
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}

function friendlyError(error: unknown, fallback: string) {
  if (error instanceof QuestionAuthenticationError) return SESSION_EXPIRED_MESSAGE
  if (error instanceof ApiNetworkError) {
    return 'Không thể kết nối đến máy chủ. Vui lòng kiểm tra kết nối và thử lại.'
  }
  if (error instanceof ApiRequestError) {
    if (error.kind === 'not-found') {
      return 'Cuộc trò chuyện không còn tồn tại hoặc bạn không có quyền truy cập.'
    }
    if (error.kind === 'validation') return error.message
  }
  return fallback
}

function App() {
  const { session } = useAuth()
  const [conversations, setConversations] = useState<Conversation[]>(() => [
    createConversation('workspace-0', consumePendingQuestion()),
  ])
  const [activeId, setActiveId] = useState('workspace-0')
  const [pendingRequest, setPendingRequest] = useState<PendingRequest | null>(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false)
  const [referencePanelOpen, setReferencePanelOpen] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState<string>()
  const [actionState, setActionState] = useState<ConversationActionState | null>(null)
  const [actionErrors, setActionErrors] = useState<Record<string, string>>({})

  const mountedRef = useRef(false)
  const conversationsRef = useRef(conversations)
  const activeIdRef = useRef(activeId)
  const requestRef = useRef<PendingRequest | null>(null)
  const historyVersionRef = useRef(0)
  const messageVersionsRef = useRef(new Map<string, number>())
  const nextWorkspaceId = useRef(1)
  const nextTurnId = useRef(1)
  const transcriptRef = useRef<HTMLDivElement>(null)
  const composerInputRef = useRef<HTMLTextAreaElement>(null)
  const mobileHistoryTriggerRef = useRef<HTMLButtonElement>(null)
  const referencePanelTriggerRef = useRef<HTMLButtonElement>(null)
  conversationsRef.current = conversations
  activeIdRef.current = activeId

  const accessToken = hasValidAccessToken(session) ? session?.access_token : undefined
  const activeConversation = useMemo(
    () => conversations.find((item) => item.id === activeId) ?? conversations[0],
    [activeId, conversations],
  )
  const persistedConversations = useMemo(
    () => conversations.filter((item) => item.serverId !== null),
    [conversations],
  )

  const fetchHistory = useCallback(
    async (signal?: AbortSignal, showLoading = true) => {
      const version = ++historyVersionRef.current
      if (!accessToken) {
        if (mountedRef.current) {
          setHistoryLoading(false)
          setHistoryError(SESSION_EXPIRED_MESSAGE)
        }
        return
      }
      if (showLoading) setHistoryLoading(true)
      setHistoryError(undefined)
      try {
        const items = await listConversations(accessToken, signal)
        if (!mountedRef.current || historyVersionRef.current !== version) return
        setConversations((current) => mergeConversationList(current, items))
      } catch (error) {
        if (
          isAbortError(error) ||
          !mountedRef.current ||
          historyVersionRef.current !== version
        ) return
        setHistoryError(friendlyError(error, HISTORY_LOAD_ERROR))
      } finally {
        if (mountedRef.current && historyVersionRef.current === version) {
          setHistoryLoading(false)
        }
      }
    },
    [accessToken],
  )

  useEffect(() => {
    mountedRef.current = true
    finishPendingQuestionConsumption()
    return () => {
      mountedRef.current = false
    }
  }, [])

  useEffect(() => {
    if (transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight
    }
  }, [activeId, activeConversation?.turns])

  useEffect(() => {
    if (activeConversation?.turns.length && !pendingRequest) {
      composerInputRef.current?.focus()
    }
  }, [activeConversation?.turns.length, activeId, pendingRequest])

  useEffect(() => {
    const controller = new AbortController()
    // Avoid the duplicate development request caused by StrictMode's first probe.
    const timer = window.setTimeout(() => void fetchHistory(controller.signal), 0)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [fetchHistory])

  const loadMessages = useCallback(
    async (conversationId: string) => {
      const conversation = conversationsRef.current.find((item) => item.id === conversationId)
      if (!conversation?.serverId) return
      if (!accessToken) {
        setConversations((current) => current.map((item) =>
          item.id === conversationId
            ? { ...item, messagesStatus: 'error', messagesError: SESSION_EXPIRED_MESSAGE }
            : item,
        ))
        return
      }

      const version = (messageVersionsRef.current.get(conversationId) ?? 0) + 1
      messageVersionsRef.current.set(conversationId, version)
      const serverId = conversation.serverId
      setConversations((current) => current.map((item) =>
        item.id === conversationId
          ? { ...item, messagesStatus: 'loading', messagesError: undefined }
          : item,
      ))

      try {
        const messages = await getConversationMessages(accessToken, serverId)
        if (!mountedRef.current || messageVersionsRef.current.get(conversationId) !== version) return
        const turns = mapMessagesToTurns(messages)
        setConversations((current) => current.map((item) =>
          item.id === conversationId && item.serverId === serverId
            ? { ...item, turns, messagesStatus: 'loaded', messagesError: undefined }
            : item,
        ))
      } catch (error) {
        if (!mountedRef.current || messageVersionsRef.current.get(conversationId) !== version) return
        setConversations((current) => current.map((item) =>
          item.id === conversationId && item.serverId === serverId
            ? {
                ...item,
                messagesStatus: 'error',
                messagesError: friendlyError(
                  error,
                  'Không thể tải nội dung cuộc trò chuyện. Vui lòng thử lại.',
                ),
              }
            : item,
        ))
      }
    },
    [accessToken],
  )

  const createNew = useCallback(() => {
    const id = `workspace-${nextWorkspaceId.current++}`
    setConversations((current) => [
      createConversation(id),
      ...current.filter((item) =>
        item.serverId !== null || requestRef.current?.conversationId === item.id,
      ),
    ])
    setActiveId(id)
    setMobileDrawerOpen(false)
    setReferencePanelOpen(false)
  }, [])

  const closeMobileDrawer = useCallback(() => {
    setMobileDrawerOpen(false)
    window.requestAnimationFrame(() => mobileHistoryTriggerRef.current?.focus())
  }, [])

  const closeReferencePanel = useCallback(() => {
    setReferencePanelOpen(false)
    window.requestAnimationFrame(() => referencePanelTriggerRef.current?.focus())
  }, [])

  const selectConversation = useCallback((conversationId: string) => {
    const conversation = conversationsRef.current.find((item) => item.id === conversationId)
    if (!conversation) return
    setActiveId(conversationId)
    setMobileDrawerOpen(false)
    setReferencePanelOpen(false)
    if (conversation.serverId && conversation.messagesStatus === 'unloaded') {
      void loadMessages(conversationId)
    }
  }, [loadMessages])

  const updateDraft = useCallback((conversationId: string, draft: string) => {
    setConversations((current) => current.map((item) =>
      item.id === conversationId ? { ...item, draft } : item,
    ))
  }, [])

  const appendTranscript = useCallback((conversationId: string, transcript: string) => {
    if (activeIdRef.current !== conversationId) return
    setConversations((current) => current.map((item) => {
      if (item.id !== conversationId) return item
      return {
        ...item,
        draft: `${item.draft}${item.draft.trim() ? ' ' : ''}${transcript.trim()}`,
      }
    }))
  }, [])

  const sendQuestion = useCallback(async (
    conversationId: string,
    text: string,
    retryTurnId?: string,
  ) => {
    const question = text.trim()
    if (!question || requestRef.current) return
    const origin = conversationsRef.current.find((item) => item.id === conversationId)
    if (!origin || origin.messagesStatus === 'loading') return

    const turnId = retryTurnId ?? `turn-${nextTurnId.current++}`
    const request = { conversationId, turnId }
    requestRef.current = request
    setPendingRequest(request)
    const pendingTurn: ChatTurn = { id: turnId, question, status: 'pending' }
    setConversations((current) => current.map((item) => {
      if (item.id !== conversationId) return item
      return {
        ...item,
        draft: '',
        title: item.titleKind === 'default' ? createConversationTitle(question) : item.title,
        titleKind: item.titleKind === 'default' ? 'generated' : item.titleKind,
        turns: retryTurnId
          ? item.turns.map((turn) => turn.id === retryTurnId ? pendingTurn : turn)
          : [...item.turns, pendingTurn],
      }
    }))

    try {
      if (!accessToken) throw new QuestionAuthenticationError()
      const response = await askQuestion(
        question,
        accessToken,
        5,
        origin.serverId ?? undefined,
      )
      if (!mountedRef.current) return
      const completedAt = Date.now()
      setConversations((current) => current.map((item) =>
        item.id === conversationId
          ? {
              ...item,
              serverId: origin.serverId ?? response.conversation_id,
              messagesStatus: 'loaded',
              updatedAt: completedAt,
              turns: item.turns.map((turn) =>
                turn.id === turnId ? { ...turn, status: 'complete', response } : turn,
              ),
            }
          : item,
      ))
      if (!origin.serverId) void fetchHistory(undefined, false)
    } catch (error) {
      if (!mountedRef.current) return
      const message = friendlyError(error, DEFAULT_REQUEST_ERROR)
      setConversations((current) => current.map((item) =>
        item.id === conversationId
          ? {
              ...item,
              turns: item.turns.map((turn) =>
                turn.id === turnId ? { ...turn, status: 'error', message } : turn,
              ),
            }
          : item,
      ))
    } finally {
      if (
        requestRef.current?.conversationId === conversationId &&
        requestRef.current.turnId === turnId
      ) {
        requestRef.current = null
        if (mountedRef.current) setPendingRequest(null)
      }
    }
  }, [accessToken, fetchHistory])

  const clearActionError = useCallback((conversationId: string) => {
    setActionErrors((current) => {
      const next = { ...current }
      delete next[conversationId]
      return next
    })
  }, [])

  const renameConversation = useCallback(async (conversationId: string, title: string) => {
    const conversation = conversationsRef.current.find((item) => item.id === conversationId)
    const trimmed = title.trim()
    if (!conversation?.serverId || !trimmed || trimmed.length > 200) return false
    if (!accessToken) {
      setActionErrors((current) => ({ ...current, [conversationId]: SESSION_EXPIRED_MESSAGE }))
      return false
    }
    setActionState({ conversationId, kind: 'rename' })
    clearActionError(conversationId)
    try {
      const updated = await updateConversation(accessToken, conversation.serverId, { title: trimmed })
      if (!mountedRef.current) return false
      setConversations((current) => current.map((item) =>
        item.id === conversationId ? applyConversationMetadata(item, updated) : item,
      ))
      return true
    } catch (error) {
      if (mountedRef.current) setActionErrors((current) => ({
        ...current,
        [conversationId]: friendlyError(error, 'Không thể đổi tên cuộc trò chuyện. Vui lòng thử lại.'),
      }))
      return false
    } finally {
      if (mountedRef.current) setActionState(null)
    }
  }, [accessToken, clearActionError])

  const togglePin = useCallback(async (conversationId: string) => {
    const conversation = conversationsRef.current.find((item) => item.id === conversationId)
    if (!conversation?.serverId || !accessToken) {
      if (!accessToken) setActionErrors((current) => ({
        ...current,
        [conversationId]: SESSION_EXPIRED_MESSAGE,
      }))
      return false
    }
    setActionState({ conversationId, kind: 'pin' })
    clearActionError(conversationId)
    try {
      const updated = await updateConversation(accessToken, conversation.serverId, {
        is_pinned: !conversation.isPinned,
      })
      if (!mountedRef.current) return false
      setConversations((current) => current.map((item) =>
        item.id === conversationId ? applyConversationMetadata(item, updated) : item,
      ))
      return true
    } catch (error) {
      if (mountedRef.current) setActionErrors((current) => ({
        ...current,
        [conversationId]: friendlyError(error, 'Không thể cập nhật trạng thái ghim. Vui lòng thử lại.'),
      }))
      return false
    } finally {
      if (mountedRef.current) setActionState(null)
    }
  }, [accessToken, clearActionError])

  const deleteConversation = useCallback(async (conversationId: string) => {
    const conversation = conversationsRef.current.find((item) => item.id === conversationId)
    if (!conversation?.serverId || requestRef.current?.conversationId === conversationId) return false
    if (!accessToken) {
      setActionErrors((current) => ({ ...current, [conversationId]: SESSION_EXPIRED_MESSAGE }))
      return false
    }
    setActionState({ conversationId, kind: 'delete' })
    clearActionError(conversationId)
    try {
      await deleteConversationRequest(accessToken, conversation.serverId)
      if (!mountedRef.current) return false
      const workspaceId = `workspace-${nextWorkspaceId.current++}`
      setConversations((current) => [
        createConversation(workspaceId),
        ...current.filter((item) => item.id !== conversationId),
      ])
      setActiveId(workspaceId)
      setReferencePanelOpen(false)
      return true
    } catch (error) {
      if (mountedRef.current) setActionErrors((current) => ({
        ...current,
        [conversationId]: friendlyError(error, 'Không thể xóa cuộc trò chuyện. Vui lòng thử lại.'),
      }))
      return false
    } finally {
      if (mountedRef.current) setActionState(null)
    }
  }, [accessToken, clearActionError])

  const retryTurn = useCallback((conversationId: string, turnId: string) => {
    const turn = conversationsRef.current
      .find((item) => item.id === conversationId)
      ?.turns.find((item) => item.id === turnId)
    if (turn) void sendQuestion(conversationId, turn.question, turnId)
  }, [sendQuestion])

  const submitActive = useCallback((question: string) => {
    if (activeConversation) void sendQuestion(activeConversation.id, question)
  }, [activeConversation, sendQuestion])

  const requestPending = pendingRequest?.conversationId === activeConversation?.id
  const hasMessages = Boolean(activeConversation?.turns.length)

  function renderComposer(helperText?: string | null, describedBy?: string) {
    if (!activeConversation) return null
    return (
      <ChatComposer
        draft={activeConversation.draft}
        conversationId={activeConversation.id}
        isPending={requestPending}
        inputRef={composerInputRef}
        onDraftChange={(draft) => updateDraft(activeConversation.id, draft)}
        onSubmit={() => submitActive(activeConversation.draft)}
        onSpeechTranscript={appendTranscript}
        helperText={helperText}
        describedBy={describedBy}
      />
    )
  }

  return (
    <div className={hasMessages ? 'app-shell app-shell--history app-shell--chat' : 'app-shell app-shell--history'} lang="vi">
      <ChatHistorySidebar
        conversations={persistedConversations}
        activeConversationId={activeConversation?.id ?? null}
        pendingConversationId={pendingRequest?.conversationId ?? null}
        isHistoryLoading={historyLoading}
        historyError={historyError}
        isCollapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed((current) => !current)}
        onCreate={createNew}
        onRetryHistory={() => void fetchHistory()}
        onSelect={selectConversation}
      />

      <div className="chat-main">
        <header className="mobile-chat-header">
          <div className="mobile-chat-header__leading">
            <button
              ref={mobileHistoryTriggerRef}
              className="mobile-history-trigger"
              type="button"
              aria-label="Mở lịch sử trò chuyện"
              aria-expanded={mobileDrawerOpen}
              aria-controls="mobile-history-drawer"
              onClick={() => setMobileDrawerOpen(true)}
            >
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
                <path d="M3.5 5.5h13M3.5 10h13M3.5 14.5h13" strokeLinecap="round" />
              </svg>
            </button>
            <a className="mobile-chat-header__brand" href="#conversation" aria-label="Đại học Văn Lang, về cuộc trò chuyện">
              <img src={vluLogo} alt="Đại học Văn Lang" width={116} height={36} />
            </a>
          </div>

          {activeConversation && (
            <CurrentConversationToolbar
              conversation={activeConversation}
              isRequestPending={requestPending}
              isActionPending={Boolean(actionState)}
              actionError={actionErrors[activeConversation.id]}
              isReferencePanelOpen={referencePanelOpen}
              referencePanelTriggerRef={referencePanelTriggerRef}
              onToggleReferencePanel={() => setReferencePanelOpen((current) => !current)}
              onRename={renameConversation}
              onTogglePin={togglePin}
              onDelete={deleteConversation}
            />
          )}
        </header>

        <div className="chat-content-layout">
          <div className="conversation-stage">
            <main
              className={activeConversation ? (hasMessages ? 'conversation conversation--active' : 'conversation conversation--empty') : 'conversation conversation--none'}
              id="conversation"
              aria-labelledby={activeConversation ? (hasMessages ? 'conversation-heading' : 'welcome-heading') : 'no-conversation-heading'}
            >
              {!activeConversation ? (
                <section className="no-conversation">
                  <h1 id="no-conversation-heading">Chưa có cuộc trò chuyện</h1>
                  <button className="new-conversation-button" type="button" onClick={createNew}>Cuộc trò chuyện mới</button>
                </section>
              ) : activeConversation.messagesStatus === 'loading' ? (
                <section className="conversation-load-state" aria-live="polite">
                  <span className="conversation-load-spinner" aria-hidden="true" />
                  <p>Đang tải nội dung cuộc trò chuyện…</p>
                </section>
              ) : activeConversation.messagesStatus === 'error' ? (
                <section className="conversation-load-state conversation-load-state--error" role="alert">
                  <p>{activeConversation.messagesError}</p>
                  <button type="button" onClick={() => void loadMessages(activeConversation.id)}>Thử lại</button>
                </section>
              ) : !hasMessages ? (
                <div className="empty-chat">
                  <section className="welcome">
                    <h1 id="welcome-heading">Bạn cần tìm thông tin gì tại Văn Lang?</h1>
                    <p>Đặt câu hỏi về chương trình đào tạo và thông tin học vụ.</p>
                  </section>
                  {renderComposer(null, 'empty-chat-helper')}
                  <SuggestedQuestions
                    onSelect={(question) => {
                      updateDraft(activeConversation.id, question)
                      window.requestAnimationFrame(() => composerInputRef.current?.focus())
                    }}
                  />
                  <p className="empty-chat__helper" id="empty-chat-helper">
                    Enter để gửi · Shift + Enter để xuống dòng. Nguồn tham chiếu sẽ hiển thị dưới câu trả lời.
                  </p>
                </div>
              ) : (
                <>
                  <ChatTranscript
                    turns={activeConversation.turns}
                    isRequestPending={requestPending}
                    containerRef={transcriptRef}
                    onRetry={(_question, turnId) => retryTurn(activeConversation.id, turnId)}
                  />
                  {renderComposer()}
                </>
              )}
            </main>
          </div>

          {activeConversation && (
            <ReferenceSourcesPanel
              conversation={activeConversation}
              isOpen={referencePanelOpen}
              onClose={closeReferencePanel}
            />
          )}
        </div>
      </div>

      <MobileHistoryDrawer
        isOpen={mobileDrawerOpen}
        conversations={persistedConversations}
        activeConversationId={activeConversation?.id ?? null}
        pendingConversationId={pendingRequest?.conversationId ?? null}
        isHistoryLoading={historyLoading}
        historyError={historyError}
        onClose={closeMobileDrawer}
        onCreate={createNew}
        onRetryHistory={() => void fetchHistory()}
        onSelect={selectConversation}
      />
    </div>
  )
}

export default App

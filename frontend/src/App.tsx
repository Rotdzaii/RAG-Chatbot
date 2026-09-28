import { useCallback, useEffect, useRef, useState } from 'react'
import { askQuestion, QuestionAuthenticationError } from './api'
import vluLogo from './assets/vlu-logo.svg'
import { useAuth } from './auth/useAuth'
import { ChatComposer } from './chat/ChatComposer'
import { CurrentConversationToolbar } from './chat/CurrentConversationToolbar'
import { ChatHistorySidebar } from './chat/ChatHistorySidebar'
import { ChatTranscript } from './chat/ChatTranscript'
import { MobileHistoryDrawer } from './chat/MobileHistoryDrawer'
import { ReferenceSourcesPanel } from './chat/ReferenceSourcesPanel'
import { SuggestedQuestions } from './chat/SuggestedQuestions'
import { createConversation, createConversationTitle, sortConversations } from './chat/conversationUtils'
import { consumePendingQuestion, finishPendingQuestionConsumption } from './chat/pendingQuestion'
import type { PendingRequest } from './chat/types'
import './App.css'

const SESSION_EXPIRED_ERROR = 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.'
const INITIAL_CONVERSATION_ID = 'conversation-0'

function App() {
  const { session } = useAuth()
  const [conversations, setConversations] = useState(() => [
    createConversation(INITIAL_CONVERSATION_ID, consumePendingQuestion()),
  ])
  const [activeConversationId, setActiveConversationId] = useState<string | null>(INITIAL_CONVERSATION_ID)
  const [pendingRequest, setPendingRequest] = useState<PendingRequest | null>(null)
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const [isMobileHistoryOpen, setIsMobileHistoryOpen] = useState(false)
  const [isReferencePanelOpen, setIsReferencePanelOpen] = useState(false)
  const requestInFlight = useRef<PendingRequest | null>(null)
  const nextConversationId = useRef(1)
  const nextTurnId = useRef(0)
  const transcript = useRef<HTMLDivElement>(null)
  const composerInput = useRef<HTMLTextAreaElement>(null)
  const mobileHistoryTrigger = useRef<HTMLButtonElement>(null)
  const referencePanelTrigger = useRef<HTMLButtonElement>(null)
  const activeConversation = conversations.find((conversation) => conversation.id === activeConversationId) ?? null
  const hasMessages = (activeConversation?.turns.length ?? 0) > 0
  const isRequestPending = pendingRequest !== null

  useEffect(() => {
    finishPendingQuestionConsumption()
  }, [])

  useEffect(() => {
    const container = transcript.current
    if (container) container.scrollTop = container.scrollHeight
  }, [activeConversationId, activeConversation?.turns])

  useEffect(() => {
    if (hasMessages && !isRequestPending) composerInput.current?.focus()
  }, [activeConversationId, hasMessages, isRequestPending])

  const closeMobileHistory = useCallback(() => {
    setIsMobileHistoryOpen(false)
    window.requestAnimationFrame(() => mobileHistoryTrigger.current?.focus())
  }, [])

  const closeReferencePanel = useCallback(() => {
    setIsReferencePanelOpen(false)
    window.requestAnimationFrame(() => referencePanelTrigger.current?.focus())
  }, [])

  function createNewConversation() {
    const conversationId = `conversation-${nextConversationId.current++}`
    setConversations((previous) => [createConversation(conversationId), ...previous])
    setActiveConversationId(conversationId)
  }

  function selectConversation(conversationId: string) {
    setActiveConversationId(conversationId)
  }

  function deleteConversation(conversationId: string) {
    if (requestInFlight.current?.conversationId === conversationId) return

    const orderedConversations = sortConversations(conversations)
    const deletedIndex = orderedConversations.findIndex((conversation) => conversation.id === conversationId)
    const remainingConversations = orderedConversations.filter((conversation) => conversation.id !== conversationId)

    if (remainingConversations.length === 0) {
      const nextConversation = createConversation(`conversation-${nextConversationId.current++}`)
      setConversations([nextConversation])
      setActiveConversationId(nextConversation.id)
      return
    }

    setConversations(remainingConversations)
    const nextConversation = remainingConversations[Math.min(Math.max(deletedIndex, 0), remainingConversations.length - 1)]
    setActiveConversationId(nextConversation.id)
  }

  function toggleConversationPin(conversationId: string) {
    setConversations((previous) => previous.map((conversation) => (
      conversation.id === conversationId
        ? { ...conversation, isPinned: !conversation.isPinned }
        : conversation
    )))
  }

  function updateConversationDraft(conversationId: string, draft: string) {
    const updatedAt = Date.now()
    setConversations((previous) => previous.map((conversation) => (
      conversation.id === conversationId ? { ...conversation, draft, updatedAt } : conversation
    )))
  }

  function fillSuggestedQuestion(conversationId: string, question: string) {
    updateConversationDraft(conversationId, question)
    window.requestAnimationFrame(() => composerInput.current?.focus())
  }

  function appendSpeechTranscript(conversationId: string, transcriptText: string) {
    if (conversationId !== activeConversationId) return

    const updatedAt = Date.now()
    setConversations((previous) => previous.map((conversation) => {
      if (conversation.id !== conversationId) return conversation

      const existingDraft = conversation.draft.trimEnd()
      return {
        ...conversation,
        draft: existingDraft ? `${existingDraft} ${transcriptText}` : transcriptText,
        updatedAt,
      }
    }))
  }

  async function sendQuestion(conversationId: string, text: string, retryTurnId?: number) {
    const trimmedQuestion = text.trim()
    if (!trimmedQuestion || requestInFlight.current) return

    const turnId = retryTurnId ?? nextTurnId.current++
    const requestOrigin = { conversationId, turnId }
    const requestStartedAt = Date.now()
    requestInFlight.current = requestOrigin
    setPendingRequest(requestOrigin)

    setConversations((previous) => previous.map((conversation) => {
      if (conversation.id !== conversationId) return conversation

      const nextTurn = { id: turnId, question: trimmedQuestion, status: 'pending' as const }
      const turns = retryTurnId === undefined
        ? [...conversation.turns, nextTurn]
        : conversation.turns.map((turn) => turn.id === turnId ? nextTurn : turn)
      const shouldGenerateTitle = retryTurnId === undefined && conversation.turns.length === 0 && conversation.titleKind === 'default'

      return {
        ...conversation,
        title: shouldGenerateTitle ? createConversationTitle(trimmedQuestion) : conversation.title,
        titleKind: shouldGenerateTitle ? 'generated' : conversation.titleKind,
        draft: retryTurnId === undefined ? '' : conversation.draft,
        turns,
        updatedAt: requestStartedAt,
      }
    }))

    try {
      const accessToken = session && (
        session.expires_at === undefined || session.expires_at > Date.now() / 1000
      ) ? session.access_token : undefined
      const response = await askQuestion(trimmedQuestion, accessToken)
      const responseReceivedAt = Date.now()

      setConversations((previous) => previous.map((conversation) => (
        conversation.id === conversationId
          ? {
              ...conversation,
              turns: conversation.turns.map((turn) => turn.id === turnId
                ? { id: turnId, question: trimmedQuestion, status: 'complete', response }
                : turn),
              updatedAt: responseReceivedAt,
            }
          : conversation
      )))
    } catch (error) {
      const responseFailedAt = Date.now()
      setConversations((previous) => previous.map((conversation) => (
        conversation.id === conversationId
          ? {
              ...conversation,
              turns: conversation.turns.map((turn) => turn.id === turnId
                ? {
                    id: turnId,
                    question: trimmedQuestion,
                    status: 'error',
                    message: error instanceof QuestionAuthenticationError
                      ? SESSION_EXPIRED_ERROR
                      : undefined,
                  }
                : turn),
              updatedAt: responseFailedAt,
            }
          : conversation
      )))
    } finally {
      if (
        requestInFlight.current?.conversationId === conversationId &&
        requestInFlight.current.turnId === turnId
      ) {
        requestInFlight.current = null
        setPendingRequest(null)
      }
    }
  }

  return (
    <div className={hasMessages ? 'app-shell app-shell--history app-shell--chat' : 'app-shell app-shell--history'} lang="vi">
      <ChatHistorySidebar
        conversations={conversations}
        activeConversationId={activeConversationId}
        pendingConversationId={pendingRequest?.conversationId ?? null}
        isCollapsed={isSidebarCollapsed}
        onToggleCollapsed={() => setIsSidebarCollapsed((collapsed) => !collapsed)}
        onCreate={createNewConversation}
        onSelect={selectConversation}
      />

      <div className="chat-main">
        <header className="mobile-chat-header">
          <div className="mobile-chat-header__leading">
            <button
              ref={mobileHistoryTrigger}
              className="mobile-history-trigger"
              type="button"
              aria-label="Mở lịch sử trò chuyện"
              aria-expanded={isMobileHistoryOpen}
              aria-controls="mobile-history-drawer"
              onClick={() => setIsMobileHistoryOpen(true)}
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
              isRequestPending={pendingRequest?.conversationId === activeConversation.id}
              isReferencePanelOpen={isReferencePanelOpen}
              referencePanelTriggerRef={referencePanelTrigger}
              onToggleReferencePanel={() => setIsReferencePanelOpen((isOpen) => !isOpen)}
              onTogglePin={toggleConversationPin}
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
              <p>Tạo một cuộc trò chuyện mới để bắt đầu đặt câu hỏi.</p>
              <button className="new-conversation-button" type="button" onClick={createNewConversation}>Cuộc trò chuyện mới</button>
            </section>
          ) : (
            <>
              {!hasMessages ? (
                <div className="empty-chat">
                  <section className="welcome">
                    <h1 id="welcome-heading">Bạn cần tìm thông tin gì tại Văn Lang?</h1>
                    <p>Đặt câu hỏi về chương trình đào tạo và thông tin học vụ.</p>
                  </section>

                  <ChatComposer
                    draft={activeConversation.draft}
                    conversationId={activeConversation.id}
                    isPending={isRequestPending}
                    inputRef={composerInput}
                    onDraftChange={(draft) => updateConversationDraft(activeConversation.id, draft)}
                    onSubmit={() => void sendQuestion(activeConversation.id, activeConversation.draft)}
                    onSpeechTranscript={appendSpeechTranscript}
                    helperText={null}
                    describedBy="empty-chat-helper"
                  />

                  <SuggestedQuestions
                    onSelect={(question) => fillSuggestedQuestion(activeConversation.id, question)}
                  />

                  <p className="empty-chat__helper" id="empty-chat-helper">
                    Enter để gửi · Shift + Enter để xuống dòng. Nguồn tham chiếu sẽ hiển thị dưới câu trả lời.
                  </p>
                </div>
              ) : (
                <>
                  <ChatTranscript
                    turns={activeConversation.turns}
                    isRequestPending={isRequestPending}
                    containerRef={transcript}
                    onRetry={(question, turnId) => void sendQuestion(activeConversation.id, question, turnId)}
                  />

                  <ChatComposer
                    draft={activeConversation.draft}
                    conversationId={activeConversation.id}
                    isPending={isRequestPending}
                    inputRef={composerInput}
                    onDraftChange={(draft) => updateConversationDraft(activeConversation.id, draft)}
                    onSubmit={() => void sendQuestion(activeConversation.id, activeConversation.draft)}
                    onSpeechTranscript={appendSpeechTranscript}
                  />
                </>
              )}
            </>
          )}
            </main>
          </div>

          {activeConversation && (
            <ReferenceSourcesPanel
              conversation={activeConversation}
              isOpen={isReferencePanelOpen}
              onClose={closeReferencePanel}
            />
          )}
        </div>
      </div>

      <MobileHistoryDrawer
        isOpen={isMobileHistoryOpen}
        conversations={conversations}
        activeConversationId={activeConversationId}
        pendingConversationId={pendingRequest?.conversationId ?? null}
        onClose={closeMobileHistory}
        onCreate={createNewConversation}
        onSelect={selectConversation}
      />
    </div>
  )
}

export default App

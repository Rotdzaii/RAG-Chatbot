import type { QuestionResponse, QuestionStage } from '../api'

export type ChatTurn = {
  id: string
  question: string
  requestId?: string
  requestConversationId?: string
} & (
  | { status: 'pending'; stage: QuestionStage | 'sending' }
  | { status: 'complete'; response: QuestionResponse }
  | { status: 'error'; message?: string }
)

export type ConversationMessagesStatus = 'new' | 'unloaded' | 'loading' | 'loaded' | 'error'

export type Conversation = {
  id: string
  serverId: string | null
  title: string
  titleKind: 'default' | 'generated' | 'custom'
  draft: string
  turns: ChatTurn[]
  isPinned: boolean
  createdAt: number
  updatedAt: number
  messagesStatus: ConversationMessagesStatus
  messagesError?: string
}

export type PendingRequest = {
  conversationId: string
  turnId: string
  controller: AbortController
}

export type ConversationActionKind = 'rename' | 'pin' | 'delete'

export type ConversationActionState = {
  conversationId: string
  kind: ConversationActionKind
} | null

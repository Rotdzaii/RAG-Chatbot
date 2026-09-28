import type { QuestionResponse } from '../api'

export type ChatTurn = {
  id: string
  question: string
} & (
  | { status: 'pending' }
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
}

export type ConversationActionKind = 'rename' | 'pin' | 'delete'

export type ConversationActionState = {
  conversationId: string
  kind: ConversationActionKind
} | null

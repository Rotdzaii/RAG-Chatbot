import type { QuestionResponse } from '../api'

export type ChatTurn = {
  id: number
  question: string
} & (
  | { status: 'pending' }
  | { status: 'complete'; response: QuestionResponse }
  | { status: 'error'; message?: string }
)

export type Conversation = {
  id: string
  title: string
  titleKind: 'default' | 'generated' | 'custom'
  draft: string
  turns: ChatTurn[]
  isPinned: boolean
  updatedAt: number
}

export type PendingRequest = {
  conversationId: string
  turnId: number
}

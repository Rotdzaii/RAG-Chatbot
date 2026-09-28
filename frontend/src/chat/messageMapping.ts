import type { ConversationMessageApiItem, QuestionSource } from '../api'
import type { ChatTurn } from './types'

function isQuestionSource(value: unknown): value is QuestionSource {
  if (typeof value !== 'object' || value === null) return false
  const source = value as Record<string, unknown>
  return typeof source.citation === 'number'
    && typeof source.chunk_id === 'string'
    && typeof source.document_id === 'string'
    && typeof source.filename === 'string'
    && typeof source.chunk_index === 'number'
    && typeof source.cosine_distance === 'number'
}

export function mapMessagesToTurns(messages: ConversationMessageApiItem[]): ChatTurn[] {
  const turns: ChatTurn[] = []

  for (let index = 0; index < messages.length; index += 1) {
    const userMessage = messages[index]
    const assistantMessage = messages[index + 1]
    if (userMessage.role !== 'user' || assistantMessage?.role !== 'assistant') continue

    turns.push({
      id: userMessage.id,
      question: userMessage.content,
      status: 'complete',
      response: {
        answer: assistantMessage.content,
        sources: (assistantMessage.citations ?? []).filter(isQuestionSource),
        conversation_id: userMessage.conversation_id,
      },
    })
    index += 1
  }

  return turns
}

import type { Conversation } from './types'

export const DEFAULT_CONVERSATION_TITLE = 'Cuộc trò chuyện mới'

export function createConversation(id: string, draft = ''): Conversation {
  return {
    id,
    title: DEFAULT_CONVERSATION_TITLE,
    titleKind: 'default',
    draft,
    turns: [],
    isPinned: false,
    updatedAt: Date.now(),
  }
}

export function sortConversations(conversations: Conversation[]) {
  return [...conversations].sort((first, second) => {
    if (first.isPinned !== second.isPinned) return first.isPinned ? -1 : 1
    return second.updatedAt - first.updatedAt
  })
}

export function createConversationTitle(question: string) {
  const normalized = question.replace(/\s+/g, ' ').trim()
  const maximumLength = 48

  if (normalized.length <= maximumLength) return normalized

  const candidate = normalized.slice(0, maximumLength - 1)
  const lastSpace = candidate.lastIndexOf(' ')
  const cutAt = lastSpace >= 30 ? lastSpace : candidate.length
  return `${candidate.slice(0, cutAt).trimEnd()}…`
}

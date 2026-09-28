import type { ConversationApiItem } from '../api'
import type { Conversation } from './types'

export const DEFAULT_CONVERSATION_TITLE = 'Cuộc trò chuyện mới'

function parseTimestamp(timestamp: string) {
  const parsed = Date.parse(timestamp)
  return Number.isNaN(parsed) ? 0 : parsed
}

export function createConversation(id: string, draft = ''): Conversation {
  const now = Date.now()
  return {
    id,
    serverId: null,
    title: DEFAULT_CONVERSATION_TITLE,
    titleKind: 'default',
    draft,
    turns: [],
    isPinned: false,
    createdAt: now,
    updatedAt: now,
    messagesStatus: 'new',
  }
}

export function createPersistedConversation(item: ConversationApiItem): Conversation {
  return {
    id: item.id,
    serverId: item.id,
    title: item.title,
    titleKind: 'generated',
    draft: '',
    turns: [],
    isPinned: item.is_pinned,
    createdAt: parseTimestamp(item.created_at),
    updatedAt: parseTimestamp(item.updated_at),
    messagesStatus: 'unloaded',
  }
}

export function applyConversationMetadata(
  conversation: Conversation,
  item: ConversationApiItem,
): Conversation {
  return {
    ...conversation,
    serverId: item.id,
    title: item.title,
    titleKind: conversation.titleKind === 'custom' ? 'custom' : 'generated',
    isPinned: item.is_pinned,
    createdAt: parseTimestamp(item.created_at),
    updatedAt: parseTimestamp(item.updated_at),
  }
}

export function mergeConversationList(
  existing: Conversation[],
  items: ConversationApiItem[],
) {
  const existingByServerId = new Map(
    existing
      .filter((conversation) => conversation.serverId)
      .map((conversation) => [conversation.serverId, conversation] as const),
  )
  const unpersisted = existing.filter((conversation) => !conversation.serverId)
  const persisted = items.map((item) => {
    const current = existingByServerId.get(item.id)
    return current
      ? applyConversationMetadata(current, item)
      : createPersistedConversation(item)
  })
  return [...unpersisted, ...persisted]
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

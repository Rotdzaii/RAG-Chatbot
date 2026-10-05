const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'

export type DocumentUploadResponse = {
  document_id: string
  filename: string
  chunk_count: number
}

export type QuestionSource = {
  citation: number
  chunk_id: string
  document_id: string
  filename: string
  chunk_index: number
  page_start?: number | null
  page_end?: number | null
  cosine_distance: number
}

export type QuestionResponse = {
  answer: string
  sources: QuestionSource[]
  conversation_id: string
}

export type ConversationApiItem = {
  id: string
  title: string
  is_pinned: boolean
  created_at: string
  updated_at: string
}

export type ConversationMessageApiItem = {
  id: string
  conversation_id: string
  role: 'user' | 'assistant'
  content: string
  citations: unknown[] | null
  created_at: string
}

export type ConversationPatch = {
  title?: string
  is_pinned?: boolean
}

export type ApiErrorKind = 'validation' | 'not-found' | 'server' | 'request'

export class QuestionAuthenticationError extends Error {
  constructor() {
    super('Authentication required')
    this.name = 'QuestionAuthenticationError'
  }
}

export class ApiRequestError extends Error {
  readonly status: number
  readonly kind: ApiErrorKind

  constructor(message: string, status: number, kind: ApiErrorKind) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
    this.kind = kind
  }
}

export class ApiNetworkError extends Error {
  constructor() {
    super('Network request failed')
    this.name = 'ApiNetworkError'
  }
}

async function readErrorMessage(response: Response) {
  try {
    const body: unknown = await response.json()
    if (
      typeof body === 'object' &&
      body !== null &&
      'detail' in body &&
      typeof body.detail === 'string'
    ) {
      return body.detail
    }
  } catch {
    // Fall through to the status-based message.
  }
  return 'Request failed'
}

function requireAccessToken(accessToken: string | undefined) {
  const token = accessToken?.trim()
  if (!token) throw new QuestionAuthenticationError()
  return token
}

async function authorizedRequest(
  path: string,
  accessToken: string | undefined,
  init: RequestInit = {},
) {
  const token = requireAccessToken(accessToken)
  let response: Response

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        ...(init.body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...init.headers,
        Authorization: `Bearer ${token}`,
      },
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiNetworkError()
  }

  if (response.status === 401) throw new QuestionAuthenticationError()
  if (!response.ok) {
    const kind: ApiErrorKind = response.status === 400 || response.status === 422
      ? 'validation'
      : response.status === 404
        ? 'not-found'
        : response.status >= 500
          ? 'server'
          : 'request'
    throw new ApiRequestError(await readErrorMessage(response), response.status, kind)
  }

  return response
}

async function throwForUploadError(response: Response): Promise<void> {
  if (response.ok) return
  throw new ApiRequestError(
    await readErrorMessage(response),
    response.status,
    response.status === 400 || response.status === 422 ? 'validation' : 'server',
  )
}

export async function uploadDocument(file: File): Promise<DocumentUploadResponse> {
  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(`${API_BASE_URL}/documents`, {
    method: 'POST',
    body: formData,
  })
  await throwForUploadError(response)
  return response.json() as Promise<DocumentUploadResponse>
}

export async function listConversations(
  accessToken: string | undefined,
  signal?: AbortSignal,
): Promise<ConversationApiItem[]> {
  const response = await authorizedRequest('/conversations', accessToken, { signal })
  return response.json() as Promise<ConversationApiItem[]>
}

export async function getConversationMessages(
  accessToken: string | undefined,
  conversationId: string,
  signal?: AbortSignal,
): Promise<ConversationMessageApiItem[]> {
  const response = await authorizedRequest(
    `/conversations/${encodeURIComponent(conversationId)}/messages`,
    accessToken,
    { signal },
  )
  return response.json() as Promise<ConversationMessageApiItem[]>
}

export async function updateConversation(
  accessToken: string | undefined,
  conversationId: string,
  patch: ConversationPatch,
): Promise<ConversationApiItem> {
  const response = await authorizedRequest(
    `/conversations/${encodeURIComponent(conversationId)}`,
    accessToken,
    { method: 'PATCH', body: JSON.stringify(patch) },
  )
  return response.json() as Promise<ConversationApiItem>
}

export async function deleteConversation(
  accessToken: string | undefined,
  conversationId: string,
): Promise<void> {
  await authorizedRequest(
    `/conversations/${encodeURIComponent(conversationId)}`,
    accessToken,
    { method: 'DELETE' },
  )
}

export async function askQuestion(
  question: string,
  accessToken: string | undefined,
  topK = 5,
  conversationId?: string,
): Promise<QuestionResponse> {
  const body: { question: string; top_k: number; conversation_id?: string } = {
    question,
    top_k: topK,
  }
  if (conversationId) body.conversation_id = conversationId

  const response = await authorizedRequest('/questions', accessToken, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return response.json() as Promise<QuestionResponse>
}

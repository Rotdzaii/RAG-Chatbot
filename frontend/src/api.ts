const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000"

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
  cosine_distance: number
}

export type QuestionResponse = {
  answer: string
  sources: QuestionSource[]
}

export class QuestionAuthenticationError extends Error {
  constructor() {
    super("Question authentication required")
    this.name = "QuestionAuthenticationError"
  }
}

async function throwForError(response: Response): Promise<void> {
  if (response.ok) {
    return
  }

  let message = "Request failed"
  try {
    const body: unknown = await response.json()
    if (
      typeof body === "object" &&
      body !== null &&
      "detail" in body &&
      typeof body.detail === "string"
    ) {
      message = body.detail
    }
  } catch {
    // Use the generic message when the error response is not JSON.
  }

  throw new Error(message)
}

export async function uploadDocument(
  file: File,
): Promise<DocumentUploadResponse> {
  const formData = new FormData()
  formData.append("file", file)

  const response = await fetch(`${API_BASE_URL}/documents`, {
    method: "POST",
    body: formData,
  })
  await throwForError(response)
  return response.json() as Promise<DocumentUploadResponse>
}

export async function askQuestion(
  question: string,
  accessToken: string | undefined,
  topK = 5,
): Promise<QuestionResponse> {
  const token = accessToken?.trim()
  if (!token) {
    throw new QuestionAuthenticationError()
  }

  const response = await fetch(`${API_BASE_URL}/questions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ question, top_k: topK }),
  })
  if (response.status === 401) {
    throw new QuestionAuthenticationError()
  }
  await throwForError(response)
  return response.json() as Promise<QuestionResponse>
}

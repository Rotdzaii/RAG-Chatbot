import { ApiNetworkError, ApiRequestError, authorizedRequest } from '../api'
import type { SourceMetadataInput } from '../api'

export type KnowledgeSource = {
  id: string
  is_active: boolean
  filename: string
  mime_type: string
  source_type: 'file' | 'url'
  source_url: string | null
  category: string | null
  audience: string | null
  created_at: string
  updated_at: string
  last_checked_at: string | null
  chunk_count: number
}

export type SourcePage = { items: KnowledgeSource[]; total: number; limit: number; offset: number }

export async function getSource(token: string, id: string, signal?: AbortSignal): Promise<KnowledgeSource> {
  return (await authorizedRequest(`/admin/knowledge-sources/${encodeURIComponent(id)}`, token, { signal })).json()
}
export type SourceMutation = { document_id: string; filename: string; chunk_count: number; status: 'updated' | 'unchanged' }
export type SourceNotification = {
  id: string
  document_id: string
  source_url: string
  baseline_hash: string
  observed_hash: string
  detected_at: string
  read_at: string | null
}

export async function listSources(token: string, offset = 0, sourceType = '', signal?: AbortSignal, limit = 20, filters: SourceMetadataInput = {}, active = ''): Promise<SourcePage> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (active) params.set('is_active', active)
  if (sourceType) params.set('source_type', sourceType)
  if (filters.category != null) params.set('category', filters.category)
  if (filters.audience != null) params.set('audience', filters.audience)
  return (await authorizedRequest(`/admin/knowledge-sources?${params}`, token, { signal })).json()
}

export async function importSourceURL(token: string, url: string, metadata: SourceMetadataInput = {}) {
  return (await authorizedRequest('/admin/knowledge-sources/url', token, {
    method: 'POST', body: JSON.stringify({ url, ...metadata }),
  })).json()
}

export async function patchSourceMetadata(token: string, id: string, metadata: SourceMetadataInput): Promise<Pick<KnowledgeSource, 'id' | 'category' | 'audience' | 'updated_at'>> {
  return (await authorizedRequest(`/admin/knowledge-sources/${encodeURIComponent(id)}/metadata`, token, {
    method: 'PATCH', body: JSON.stringify(metadata),
  })).json()
}

export async function replaceSourceFile(token: string, id: string, file: File): Promise<SourceMutation> {
  const body = new FormData()
  body.append('file', file)
  return (await authorizedRequest(`/admin/knowledge-sources/${encodeURIComponent(id)}/file`, token, { method: 'PUT', body })).json()
}

export async function refreshSourceURL(token: string, id: string): Promise<SourceMutation> {
  return (await authorizedRequest(`/admin/knowledge-sources/${encodeURIComponent(id)}/refresh`, token, { method: 'POST' })).json()
}

export async function deleteSource(token: string, id: string) {
  await authorizedRequest(`/admin/knowledge-sources/${encodeURIComponent(id)}`, token, { method: 'DELETE' })
}

export async function listNotifications(token: string, offset = 0, unreadOnly = false, signal?: AbortSignal): Promise<SourceNotification[]> {
  const params = new URLSearchParams({ limit: '20', offset: String(offset), unread_only: String(unreadOnly) })
  return (await authorizedRequest(`/admin/source-change-notifications?${params}`, token, { signal })).json()
}

export async function markNotificationRead(token: string, id: string): Promise<SourceNotification> {
  return (await authorizedRequest(`/admin/source-change-notifications/${encodeURIComponent(id)}/read`, token, { method: 'POST' })).json()
}

export function sourceFile(file: File): File {
  if (!/\.(pdf|txt)$/i.test(file.name)) throw new Error('Chọn tài liệu PDF hoặc TXT.')
  if (!file.size) throw new Error('Tài liệu đang trống. Hãy chọn file khác.')
  if (file.size > 10 * 1024 * 1024) throw new Error('Tài liệu vượt quá 10 MiB. Hãy chọn file nhỏ hơn.')
  return new File([file], file.name, { type: /\.pdf$/i.test(file.name) ? 'application/pdf' : 'text/plain' })
}

export function adminError(error: unknown): string {
  if (error instanceof ApiNetworkError) return 'Không kết nối được máy chủ. Kiểm tra kết nối rồi thử lại.'
  if (error instanceof ApiRequestError) {
    const messages: Record<number, string> = {
      400: 'Dữ liệu chưa hợp lệ. Kiểm tra tài liệu hoặc địa chỉ URL.',
      404: 'Nguồn hoặc thông báo không còn tồn tại. Hãy tải lại danh sách.',
      409: 'Nguồn đã tồn tại hoặc vừa được thay đổi. Hãy tải lại danh sách trước khi thử lại.',
      413: 'Nguồn vượt giới hạn 10 MiB. Hãy chọn tài liệu nhỏ hơn.',
      415: 'Định dạng không được hỗ trợ. Hãy dùng PDF, TXT hoặc trang web VLU có nội dung văn bản.',
      422: 'Không đọc được nội dung hợp lệ. Kiểm tra tài liệu, mã hóa UTF-8 của TXT hoặc URL.',
      502: 'Không tải được nguồn URL. Kiểm tra địa chỉ và thử lại sau.',
      503: 'Dịch vụ tạm thời chưa sẵn sàng. Hãy thử lại sau.',
    }
    return messages[error.status] ?? 'Thao tác chưa hoàn tất. Hãy tải lại danh sách để kiểm tra trước khi thử lại.'
  }
  return 'Thao tác chưa hoàn tất. Hãy thử lại sau.'
}

export async function patchSourceStatus(token: string, id: string, is_active: boolean) {
  return (await authorizedRequest(`/admin/knowledge-sources/${encodeURIComponent(id)}/status`, token, {
    method: 'PATCH', body: JSON.stringify({ is_active }),
  })).json()
}

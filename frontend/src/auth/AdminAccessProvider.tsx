import { useCallback, useEffect, useMemo, useState } from 'react'
import type { PropsWithChildren } from 'react'
import { ApiNetworkError, ApiRequestError, authorizedRequest, QuestionAuthenticationError } from '../api'
import { AdminAccessContext } from './AdminAccessContext'
import type { AdminAccessStatus } from './AdminAccessContext'
import { useAuth } from './useAuth'

export function AdminAccessProvider({ children }: PropsWithChildren) {
  const { session, isLoading } = useAuth()
  const token = session?.access_token ?? ''
  const [revision, setRevision] = useState(0)
  const key = `${token}:${revision}`
  const [result, setResult] = useState<{ key: string; status: AdminAccessStatus; error?: string }>()
  const retry = useCallback(() => setRevision(value => value + 1), [])
  const handleFailure = useCallback((error: unknown) => {
    if (error instanceof QuestionAuthenticationError) setResult({ key, status: 'expired' })
    else if (error instanceof ApiRequestError && error.status === 403) setResult({ key, status: 'user' })
  }, [key])

  useEffect(() => {
    if (!token || isLoading) return
    const controller = new AbortController()
    void authorizedRequest('/auth/session', token, { signal: controller.signal })
      .then(response => response.json())
      .then((body: { role?: unknown } | null) => {
        if (controller.signal.aborted) return
        const role = body?.role
        if (role !== 'admin' && role !== 'user') throw new Error('Invalid session role')
        setResult({ key, status: role })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        if (error instanceof QuestionAuthenticationError) {
          setResult({ key, status: 'expired' })
          return
        }
        const message = error instanceof ApiNetworkError
          ? 'Không kết nối được máy chủ. Kiểm tra kết nối rồi thử lại.'
          : 'Chưa xác nhận được quyền của phiên đăng nhập. Vui lòng thử lại.'
        setResult({ key, status: 'error', error: message })
      })
    return () => controller.abort()
  }, [token, isLoading, key])

  const status = isLoading ? 'checking' : !token ? 'anonymous' : result?.key === key ? result.status : 'checking'
  const error = result?.key === key ? result.error : undefined
  const value = useMemo(() => ({ status, error, retry, handleFailure }), [status, error, retry, handleFailure])
  return <AdminAccessContext value={value}>{children}</AdminAccessContext>
}

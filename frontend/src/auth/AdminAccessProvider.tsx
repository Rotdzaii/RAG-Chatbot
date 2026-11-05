import { useCallback, useEffect, useMemo, useState } from 'react'
import type { PropsWithChildren } from 'react'
import { ApiRequestError, QuestionAuthenticationError } from '../api'
import { adminError, listSources } from '../admin/adminApi'
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
    // The protected backend endpoint is the authority; no role is persisted locally.
    void listSources(token, 0, '', controller.signal, 1).then(() => {
      if (!controller.signal.aborted) setResult({ key, status: 'admin' })
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return
      if (error instanceof QuestionAuthenticationError) setResult({ key, status: 'expired' })
      else if (error instanceof ApiRequestError && error.status === 403) setResult({ key, status: 'user' })
      else setResult({ key, status: 'error', error: adminError(error) })
    })
    return () => controller.abort()
  }, [token, isLoading, key])

  const status = isLoading ? 'checking' : !token ? 'anonymous' : result?.key === key ? result.status : 'checking'
  const error = result?.key === key ? result.error : undefined
  const value = useMemo(() => ({ status, error, retry, handleFailure }), [status, error, retry, handleFailure])
  return <AdminAccessContext value={value}>{children}</AdminAccessContext>
}

import { useEffect, useRef, useState } from 'react'
import { adminError } from './adminApi'

export function useAdminResource<T>(key: string, load: (signal: AbortSignal) => Promise<T>, onFailure: (error: unknown) => void): { loading: boolean; data?: T; error?: string } {
  const [result, setResult] = useState<{ key: string; data?: T; error?: string }>()
  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal).then(data => {
      if (!controller.signal.aborted) setResult({ key, data })
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return
      onFailure(error)
      setResult({ key, error: adminError(error) })
    })
    return () => controller.abort()
  }, [key, load, onFailure])
  return result?.key === key ? { ...result, loading: false } : { loading: true }
}

export function useAdminMutation(onFailure: (error: unknown) => void) {
  const lock = useRef(false)
  const mounted = useRef(false)
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  async function run(operation: () => Promise<string>, onSuccess: () => void) {
    if (lock.current) return
    lock.current = true
    setPending(true)
    setMessage('')
    setError('')
    try {
      const message = await operation()
      if (mounted.current) { setMessage(message); onSuccess() }
    } catch (error) {
      if (mounted.current) { onFailure(error); setError(adminError(error)) }
    } finally {
      lock.current = false
      if (mounted.current) setPending(false)
    }
  }
  return { pending, message, error, run, clear: () => { setMessage(''); setError('') } }
}

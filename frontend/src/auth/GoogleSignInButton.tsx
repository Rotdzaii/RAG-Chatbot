import { useRef, useState } from 'react'
import { useAuth } from './useAuth'

export function GoogleSignInButton({ beforeSignIn }: { beforeSignIn?: () => boolean }) {
  const { signInWithGoogle } = useAuth()
  const inFlight = useRef(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')

  async function handleSignIn() {
    if (inFlight.current || (beforeSignIn && !beforeSignIn())) return
    inFlight.current = true
    setPending(true)
    setError('')
    try {
      const { error } = await signInWithGoogle()
      if (error) setError('Chưa thể mở đăng nhập Google. Vui lòng thử lại hoặc tiếp tục bằng email.')
    } catch {
      setError('Chưa thể mở đăng nhập Google. Vui lòng thử lại hoặc tiếp tục bằng email.')
    } finally {
      inFlight.current = false
      setPending(false)
    }
  }

  return <>
    <button type="button" className="google-sign-in" disabled={pending} onClick={() => void handleSignIn()}>
      <svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor"><path d="M21.6 12.2c0-.7-.1-1.4-.2-2.1H12v3.8h5.4a4.6 4.6 0 0 1-2 3v2.5h3.2c1.9-1.8 3-4.2 3-7.2Z" /><path d="M12 22c2.7 0 5-.9 6.6-2.6l-3.2-2.5c-.9.6-2 1-3.4 1-2.6 0-4.8-1.8-5.6-4.2H3.1v2.6A10 10 0 0 0 12 22Z" /><path d="M6.4 13.7a6 6 0 0 1 0-3.4V7.7H3.1a10 10 0 0 0 0 8.6l3.3-2.6Z" /><path d="M12 6.1c1.5 0 2.8.5 3.8 1.5l2.9-2.8A9.6 9.6 0 0 0 12 2a10 10 0 0 0-8.9 5.7l3.3 2.6c.8-2.4 3-4.2 5.6-4.2Z" /></svg>
      {pending ? 'Đang mở Google…' : 'Tiếp tục bằng Google'}
    </button>
    {error && <p className="login-message login-message--error" role="alert">{error}</p>}
  </>
}

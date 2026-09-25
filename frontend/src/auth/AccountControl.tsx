import { useState } from 'react'
import { useAuth } from './useAuth'

export function AccountControl() {
  const { user, signOut } = useAuth()
  const [isPending, setIsPending] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')

  async function handleSignOut() {
    if (isPending) return

    setIsPending(true)
    setErrorMessage('')

    try {
      const { error } = await signOut()

      if (error) {
        setErrorMessage('Không thể đăng xuất. Vui lòng thử lại.')
      }
    } catch {
      setErrorMessage('Không thể đăng xuất. Vui lòng thử lại.')
    } finally {
      setIsPending(false)
    }
  }

  return (
    <div className="account-control">
      <div className="account-control__row">
        {user?.email && (
          <span className="account-email" title={user.email}>{user.email}</span>
        )}
        <button
          className="logout-button"
          type="button"
          disabled={isPending}
          aria-label={isPending ? 'Đang đăng xuất' : 'Đăng xuất'}
          aria-describedby={errorMessage ? 'logout-error' : undefined}
          onClick={() => void handleSignOut()}
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
            <path d="M8 4H4.75A1.75 1.75 0 0 0 3 5.75v8.5C3 15.22 3.78 16 4.75 16H8M12.5 6.5 16 10l-3.5 3.5M7 10h9" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span>{isPending ? 'Đang đăng xuất…' : 'Đăng xuất'}</span>
        </button>
      </div>
      {errorMessage && <p className="logout-error" id="logout-error" role="alert">{errorMessage}</p>}
    </div>
  )
}

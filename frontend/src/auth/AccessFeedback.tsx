import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import vluLogo from '../assets/vlu-logo.svg'
import { AuthLoadingScreen } from './AuthLoadingScreen'
import { useAdminAccess } from './useAdminAccess'
import { useAuth } from './useAuth'

export function AccessFeedback() {
  const { status, error, retry } = useAdminAccess()
  const { signOut } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [pending, setPending] = useState(false)
  const [signOutError, setSignOutError] = useState('')

  async function loginAgain() {
    if (pending) return
    setPending(true)
    setSignOutError('')
    try {
      const { error } = await signOut()
      if (error) { setSignOutError('Chưa thể kết thúc phiên. Vui lòng thử lại.'); return }
      const from = location.pathname === '/login' ? undefined : location.pathname
      navigate('/login', { replace: true, state: from ? { from } : undefined })
    } catch { setSignOutError('Chưa thể kết thúc phiên. Vui lòng thử lại.') }
    finally { setPending(false) }
  }

  if (status === 'checking' || status === 'anonymous') return <AuthLoadingScreen label="Đang xác nhận quyền truy cập…" />
  return <div className="access-feedback">
    <Link to="/"><img src={vluLogo} width="148" alt="Đại học Văn Lang" /></Link>
    <main><h1>{status === 'user' ? 'Bạn chưa có quyền quản trị' : status === 'expired' ? 'Phiên đăng nhập đã hết hạn' : 'Chưa thể xác nhận quyền truy cập'}</h1>
      {status === 'user' ? <p>Trang này dành cho tài khoản quản trị được cấp quyền.</p>
        : status === 'expired' ? <><p>Đăng nhập lại để tiếp tục.</p><button className="access-feedback__button" disabled={pending} onClick={() => void loginAgain()}>Đăng nhập lại</button>{signOutError && <p role="alert">{signOutError}</p>}</>
          : <><p role="alert">{error}</p><button className="access-feedback__button" onClick={retry}>Thử lại</button></>}
      <Link className="access-feedback__chat" to="/chat">Về trò chuyện</Link>
    </main>
  </div>
}

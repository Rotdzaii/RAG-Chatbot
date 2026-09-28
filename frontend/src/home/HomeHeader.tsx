import { Link } from 'react-router'
import vluLogo from '../assets/vlu-logo.svg'
import { useAuth } from '../auth/useAuth'

export function HomeHeader() {
  const { user, isLoading } = useAuth()

  return (
    <header className="home-header">
      <Link className="home-brand" to="/" aria-label="Đại học Văn Lang, trang chủ">
        <img src={vluLogo} alt="Đại học Văn Lang" width={144} height={44} />
      </Link>

      {isLoading ? (
        <span className="home-header__status" role="status">Đang kiểm tra phiên…</span>
      ) : (
        <Link className="home-header__action" to={user ? '/chat' : '/login'}>
          {user ? 'Vào trò chuyện' : 'Đăng nhập'}
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
            <path d="M5 10h10m-4-4 4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </Link>
      )}
    </header>
  )
}

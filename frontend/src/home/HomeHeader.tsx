import { Link } from 'react-router'
import vluLogo from '../assets/vlu-logo.svg'

export function HomeHeader({ onLogin }: { onLogin: () => void }) {
  return (
    <header className="home-header">
      <Link className="home-brand" to="/" aria-label="Đại học Văn Lang, trang chủ">
        <img src={vluLogo} alt="Đại học Văn Lang" width={144} height={44} />
      </Link>

      <button type="button" className="home-header__action" onClick={onLogin}>
        Đăng nhập
        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
          <path d="M5 10h10m-4-4 4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </header>
  )
}

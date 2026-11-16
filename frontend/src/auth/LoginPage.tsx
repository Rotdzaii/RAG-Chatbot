import vluLogo from '../assets/vlu-logo.svg'
import { AuthCarousel } from './AuthCarousel'
import { AuthForm } from './AuthForm'
import { GoogleSignInButton } from './GoogleSignInButton'
import { useLocation } from 'react-router'
import '../home/HomeLoginDialog.css'

export function LoginPage() {
  const location = useLocation()
  const callbackParams = new URLSearchParams(`${location.search.slice(1)}&${location.hash.slice(1)}`)
  const callbackFailed = ['error', 'error_code', 'error_description', 'access_token', 'code'].some(key => callbackParams.has(key))
  return (
    <main className="login-page" lang="vi">
      <section className="login-panel" aria-labelledby="auth-heading">
        <div className="login-panel__inner">
          <img className="login-logo" src={vluLogo} alt="Đại học Văn Lang" width={154} height={47} />
          <div className="login-google-options">
            {callbackFailed && <p role="alert">Đăng nhập Google chưa hoàn tất hoặc đã bị hủy. Câu nháp vẫn được giữ. Bạn có thể thử lại hoặc đăng nhập bằng email.</p>}
            <GoogleSignInButton />
          </div>
          <AuthForm />
        </div>
      </section>

      <AuthCarousel />
    </main>
  )
}

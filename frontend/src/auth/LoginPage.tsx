import vluLogo from '../assets/vlu-logo.svg'
import { AuthCarousel } from './AuthCarousel'
import { AuthForm } from './AuthForm'

export function LoginPage() {
  return (
    <main className="login-page" lang="vi">
      <section className="login-panel" aria-labelledby="auth-heading">
        <div className="login-panel__inner">
          <img className="login-logo" src={vluLogo} alt="Đại học Văn Lang" width={154} height={47} />
          <AuthForm />
        </div>
      </section>

      <AuthCarousel />
    </main>
  )
}

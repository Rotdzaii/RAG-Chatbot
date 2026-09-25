import vluLogo from '../assets/vlu-logo.svg'

export function AuthLoadingScreen() {
  return (
    <main className="auth-loading" lang="vi">
      <div className="auth-loading__content" role="status" aria-live="polite">
        <img src={vluLogo} alt="Đại học Văn Lang" width={154} height={47} />
        <span className="auth-loading__indicator" aria-hidden="true" />
        <span className="auth-loading__label">Đang chuẩn bị trợ lý…</span>
      </div>
    </main>
  )
}

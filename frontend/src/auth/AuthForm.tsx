import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { PasswordField } from './PasswordField'
import { useAuth } from './useAuth'

type AuthMode = 'login' | 'signup'

const LOGIN_ERROR = 'Email hoặc mật khẩu không chính xác. Vui lòng thử lại.'
const SIGNUP_ERROR = 'Không thể đăng ký tài khoản. Vui lòng thử lại.'
const PASSWORD_MISMATCH_ERROR = 'Mật khẩu xác nhận không khớp. Vui lòng kiểm tra lại.'
const CONFIRMATION_MESSAGE = 'Vui lòng kiểm tra email và làm theo hướng dẫn xác nhận để hoàn tất đăng ký.'

export function AuthForm() {
  const { signIn, signUp } = useAuth()
  const submissionInFlight = useRef(false)
  const [mode, setMode] = useState<AuthMode>('login')
  const [email, setEmail] = useState('')
  const [isPending, setIsPending] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [successMessage, setSuccessMessage] = useState('')
  const [passwordResetKey, setPasswordResetKey] = useState(0)
  const isLogin = mode === 'login'
  const feedbackId = errorMessage ? 'auth-error' : undefined

  function switchMode(nextMode: AuthMode) {
    if (nextMode === mode) return

    submissionInFlight.current = false
    setMode(nextMode)
    setIsPending(false)
    setErrorMessage('')
    setSuccessMessage('')
    setPasswordResetKey((key) => key + 1)
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submissionInFlight.current) return

    const formData = new FormData(event.currentTarget)
    const submittedEmail = String(formData.get('email') ?? '').trim()
    const password = String(formData.get('password') ?? '')

    if (!isLogin && password !== String(formData.get('passwordConfirmation') ?? '')) {
      setSuccessMessage('')
      setErrorMessage(PASSWORD_MISMATCH_ERROR)
      return
    }

    submissionInFlight.current = true
    setIsPending(true)
    setErrorMessage('')
    setSuccessMessage('')

    try {
      if (isLogin) {
        const { error } = await signIn(submittedEmail, password)

        if (error) {
          setErrorMessage(LOGIN_ERROR)
        }
      } else {
        const { data, error } = await signUp(submittedEmail, password)

        if (error) {
          setErrorMessage(SIGNUP_ERROR)
        } else if (!data.session) {
          setSuccessMessage(CONFIRMATION_MESSAGE)
          setPasswordResetKey((key) => key + 1)
        }
      }
    } catch {
      setErrorMessage(isLogin ? LOGIN_ERROR : SIGNUP_ERROR)
    } finally {
      submissionInFlight.current = false
      setIsPending(false)
    }
  }

  return (
    <div className="auth-form-stage" key={mode}>
      <div className="login-intro">
        <p className="login-eyebrow">Trợ lý tư vấn chương trình đào tạo</p>
        <h1 id="auth-heading">{isLogin ? 'Đăng nhập để tiếp tục' : 'Đăng ký tài khoản'}</h1>
        <p>
          {isLogin
            ? 'Đăng nhập để truy cập trợ lý tư vấn chương trình đào tạo tại Văn Lang.'
            : 'Tạo tài khoản bằng email để truy cập trợ lý tư vấn chương trình đào tạo.'}
        </p>
      </div>

      <form className="login-form" onSubmit={(event) => void handleSubmit(event)}>
        <div className="login-field">
          <label htmlFor="auth-email">Email</label>
          <input
            id="auth-email"
            name="email"
            type="email"
            autoComplete="email"
            inputMode="email"
            required
            disabled={isPending}
            value={email}
            aria-describedby={feedbackId}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>

        <PasswordField
          key={`${mode}-password-${passwordResetKey}`}
          id={`${mode}-password`}
          name="password"
          label="Mật khẩu"
          autoComplete={isLogin ? 'current-password' : 'new-password'}
          disabled={isPending}
          describedBy={feedbackId}
        />

        {!isLogin && (
          <PasswordField
            key={`confirmation-${passwordResetKey}`}
            id="signup-password-confirmation"
            name="passwordConfirmation"
            label="Xác nhận mật khẩu"
            autoComplete="new-password"
            disabled={isPending}
            describedBy={feedbackId}
          />
        )}

        {errorMessage && (
          <p className="login-message login-message--error" id="auth-error" role="alert">
            {errorMessage}
          </p>
        )}

        {successMessage && (
          <p className="login-message login-message--success" role="status">
            {successMessage}
          </p>
        )}

        <button className="login-submit" type="submit" disabled={isPending}>
          {isPending && <span className="button-spinner" aria-hidden="true" />}
          <span>
            {isPending
              ? (isLogin ? 'Đang đăng nhập…' : 'Đang đăng ký…')
              : (isLogin ? 'Đăng nhập' : 'Đăng ký')}
          </span>
        </button>
      </form>

      <p className="auth-mode-switch">
        <span>{isLogin ? 'Chưa có tài khoản?' : 'Đã có tài khoản?'}</span>{' '}
        <button
          type="button"
          disabled={isPending}
          onClick={() => switchMode(isLogin ? 'signup' : 'login')}
        >
          {isLogin ? 'Đăng ký' : 'Đăng nhập'}
        </button>
      </p>
    </div>
  )
}

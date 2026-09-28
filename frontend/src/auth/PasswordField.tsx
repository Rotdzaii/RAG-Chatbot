import { useState } from 'react'

type PasswordFieldProps = {
  id: string
  name: string
  label: string
  autoComplete: 'current-password' | 'new-password'
  disabled: boolean
  describedBy?: string
}

export function PasswordField({
  id,
  name,
  label,
  autoComplete,
  disabled,
  describedBy,
}: PasswordFieldProps) {
  const [isVisible, setIsVisible] = useState(false)
  const visibilityLabel = isVisible ? `Ẩn ${label.toLocaleLowerCase('vi')}` : `Hiện ${label.toLocaleLowerCase('vi')}`

  return (
    <div className="login-field">
      <label htmlFor={id}>{label}</label>
      <div className="password-input">
        <input
          id={id}
          name={name}
          type={isVisible ? 'text' : 'password'}
          autoComplete={autoComplete}
          required
          disabled={disabled}
          aria-describedby={describedBy}
        />
        <button
          type="button"
          className="password-toggle"
          aria-label={visibilityLabel}
          title={visibilityLabel}
          disabled={disabled}
          onClick={() => setIsVisible((visible) => !visible)}
        >
          {isVisible ? (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
              <path d="M3 3l18 18M10.6 10.7a2 2 0 0 0 2.7 2.7M9.4 5.3A10.5 10.5 0 0 1 12 5c5.3 0 8.5 5.1 8.5 5.1a11.9 11.9 0 0 1-2.1 2.8M6.2 6.2c-1.7 1.1-2.7 2.6-2.7 2.6S6.7 15 12 15c1 0 1.9-.2 2.8-.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
              <path d="M3.5 12S6.7 6.8 12 6.8 20.5 12 20.5 12 17.3 17.2 12 17.2 3.5 12 3.5 12Z" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="12" cy="12" r="2.3" />
            </svg>
          )}
        </button>
      </div>
    </div>
  )
}

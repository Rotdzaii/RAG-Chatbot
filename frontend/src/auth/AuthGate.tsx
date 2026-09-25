import type { PropsWithChildren } from 'react'
import { AuthLoadingScreen } from './AuthLoadingScreen'
import { LoginPage } from './LoginPage'
import { useAuth } from './useAuth'
import './auth.css'

export function AuthGate({ children }: PropsWithChildren) {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return <AuthLoadingScreen />
  }

  if (!user) {
    return <LoginPage />
  }

  return children
}

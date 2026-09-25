import type { PropsWithChildren } from 'react'
import { Navigate, useLocation } from 'react-router'
import { AuthLoadingScreen } from './AuthLoadingScreen'
import { useAuth } from './useAuth'
import './auth.css'

type AuthGateProps = PropsWithChildren<{
  access: 'guest' | 'protected'
}>

type IntendedRouteState = {
  from?: unknown
}

function getIntendedRoute(state: unknown) {
  if (
    typeof state === 'object' &&
    state !== null &&
    'from' in state
  ) {
    const { from } = state as IntendedRouteState

    if (typeof from === 'string' && from.startsWith('/') && !from.startsWith('//')) {
      return from
    }
  }

  return '/chat'
}

export function AuthGate({ children, access }: AuthGateProps) {
  const { user, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return <AuthLoadingScreen />
  }

  if (access === 'protected' && !user) {
    const intendedRoute = `${location.pathname}${location.search}${location.hash}`
    return <Navigate to="/login" state={{ from: intendedRoute }} replace />
  }

  if (access === 'guest' && user) {
    return <Navigate to={getIntendedRoute(location.state)} replace />
  }

  return children
}

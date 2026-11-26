import { matchPath, Navigate } from 'react-router'
import { AccessFeedback } from './AccessFeedback'
import { useAdminAccess } from './useAdminAccess'

export function PostLoginRedirect({ intendedRoute }: { intendedRoute?: string }) {
  const { status } = useAdminAccess()
  if (status !== 'admin' && status !== 'user') return <AccessFeedback />
  const intendedPath = intendedRoute?.split(/[?#]/, 1)[0]
  const allowedPaths = status === 'admin' ? ['/admin', '/admin/sources', '/admin/notifications'] : ['/chat']
  const canResume = intendedPath && allowedPaths.some(path => matchPath(path, intendedPath))
  return <Navigate to={canResume && intendedRoute ? intendedRoute : allowedPaths[0]} replace />
}

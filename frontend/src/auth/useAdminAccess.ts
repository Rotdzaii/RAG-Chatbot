import { useContext } from 'react'
import { AdminAccessContext } from './AdminAccessContext'

export function useAdminAccess() {
  const access = useContext(AdminAccessContext)
  if (!access) throw new Error('useAdminAccess requires AdminAccessProvider')
  return access
}

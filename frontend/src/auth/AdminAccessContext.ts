import { createContext } from 'react'

export type AdminAccessStatus = 'anonymous' | 'checking' | 'admin' | 'user' | 'expired' | 'error'
export type AdminAccessValue = {
  status: AdminAccessStatus
  error?: string
  retry: () => void
  handleFailure: (error: unknown) => void
}

export const AdminAccessContext = createContext<AdminAccessValue | undefined>(undefined)

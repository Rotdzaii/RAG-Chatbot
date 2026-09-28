import { createContext } from 'react'
import type { Session, User } from '@supabase/supabase-js'
import { supabase } from './supabase'

type SignInResult = Awaited<ReturnType<typeof supabase.auth.signInWithPassword>>
type SignUpResult = Awaited<ReturnType<typeof supabase.auth.signUp>>
type SignOutResult = Awaited<ReturnType<typeof supabase.auth.signOut>>

export type AuthContextValue = {
  session: Session | null
  user: User | null
  isLoading: boolean
  signIn: (email: string, password: string) => Promise<SignInResult>
  signUp: (email: string, password: string) => Promise<SignUpResult>
  signOut: () => Promise<SignOutResult>
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)

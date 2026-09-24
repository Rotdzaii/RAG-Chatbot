import { useCallback, useEffect, useMemo, useState } from 'react'
import type { PropsWithChildren } from 'react'
import type { Session } from '@supabase/supabase-js'
import { AuthContext } from './AuthContext'
import { supabase } from './supabase'

export function AuthProvider({ children }: PropsWithChildren) {
  const [session, setSession] = useState<Session | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    let isActive = true
    let receivedAuthEvent = false

    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (_event, nextSession) => {
        if (!isActive) return

        receivedAuthEvent = true
        setSession(nextSession)
        setIsLoading(false)
      },
    )

    void supabase.auth.getSession().then(({ data: { session: restoredSession } }) => {
      if (!isActive) return

      if (!receivedAuthEvent) {
        setSession(restoredSession)
      }
      setIsLoading(false)
    })

    return () => {
      isActive = false
      subscription.unsubscribe()
    }
  }, [])

  const signIn = useCallback((email: string, password: string) => (
    supabase.auth.signInWithPassword({ email, password })
  ), [])

  const signUp = useCallback((email: string, password: string) => (
    supabase.auth.signUp({ email, password })
  ), [])

  const signOut = useCallback(() => supabase.auth.signOut(), [])

  const value = useMemo(() => ({
    session,
    user: session?.user ?? null,
    isLoading,
    signIn,
    signUp,
    signOut,
  }), [isLoading, session, signIn, signOut, signUp])

  return <AuthContext value={value}>{children}</AuthContext>
}

import { createClient } from '@supabase/supabase-js'
import type { SupabaseClient } from '@supabase/supabase-js'

function requireEnvironmentVariable(name: string, value: string | undefined) {
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`)
  }

  return value
}

const supabaseUrl = requireEnvironmentVariable(
  'VITE_SUPABASE_URL',
  import.meta.env.VITE_SUPABASE_URL,
)
const supabasePublishableKey = requireEnvironmentVariable(
  'VITE_SUPABASE_PUBLISHABLE_KEY',
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY,
)

export const supabase: SupabaseClient = createClient(
  supabaseUrl,
  supabasePublishableKey,
  {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  },
)

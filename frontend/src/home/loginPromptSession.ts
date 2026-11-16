const PROMPT_KEY = 'vlu.home-login-prompt-seen'
let handledWithoutStorage = false

export function hasHandledLoginPrompt() {
  if (handledWithoutStorage) return true
  try {
    return sessionStorage.getItem(PROMPT_KEY) === 'true'
  } catch {
    return handledWithoutStorage
  }
}

export function markLoginPromptHandled() {
  handledWithoutStorage = true
  try {
    sessionStorage.setItem(PROMPT_KEY, 'true')
  } catch {
    // Keep the one-time behavior in memory when tab storage is unavailable.
  }
}

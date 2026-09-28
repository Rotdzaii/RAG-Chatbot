/** The only sessionStorage entry used to hand a landing-page question to chat. */
export const PENDING_QUESTION_STORAGE_KEY = 'vlu.pending-chat-question'

let pendingQuestionDuringMount: string | undefined

export function storePendingQuestion(question: string) {
  try {
    window.sessionStorage.setItem(PENDING_QUESTION_STORAGE_KEY, question)
    return true
  } catch {
    return false
  }
}

export function consumePendingQuestion() {
  if (pendingQuestionDuringMount !== undefined) {
    return pendingQuestionDuringMount
  }

  try {
    pendingQuestionDuringMount = window.sessionStorage.getItem(PENDING_QUESTION_STORAGE_KEY)?.trim() ?? ''
    window.sessionStorage.removeItem(PENDING_QUESTION_STORAGE_KEY)
  } catch {
    pendingQuestionDuringMount = ''
  }

  return pendingQuestionDuringMount
}

export function finishPendingQuestionConsumption() {
  pendingQuestionDuringMount = undefined
}

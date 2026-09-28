import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

type RecognitionAlternative = {
  transcript: string
}

type RecognitionResult = {
  isFinal: boolean
  [index: number]: RecognitionAlternative
}

type RecognitionEvent = Event & {
  resultIndex: number
  results: {
    length: number
    [index: number]: RecognitionResult
  }
}

type RecognitionErrorEvent = Event & {
  error: string
}

type BrowserSpeechRecognition = {
  lang: string
  continuous: boolean
  interimResults: boolean
  onresult: ((event: RecognitionEvent) => void) | null
  onerror: ((event: RecognitionErrorEvent) => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
  abort: () => void
}

type BrowserSpeechRecognitionConstructor = new () => BrowserSpeechRecognition

type SpeechRecognitionWindow = Window & {
  SpeechRecognition?: BrowserSpeechRecognitionConstructor
  webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor
}

type SpeechState = 'idle' | 'listening' | 'stopping'

type UseVietnameseSpeechRecognitionOptions = {
  conversationId: string
  disabled: boolean
  onFinalTranscript: (conversationId: string, transcript: string) => void
}

const UNSUPPORTED_MESSAGE = 'Trình duyệt này chưa hỗ trợ nhập bằng giọng nói.'
const PERMISSION_MESSAGE = 'Không thể truy cập micrô. Vui lòng kiểm tra quyền micrô.'
const RECOGNITION_ERROR_MESSAGE = 'Không thể nhận dạng giọng nói. Vui lòng thử lại.'

export function useVietnameseSpeechRecognition({
  conversationId,
  disabled,
  onFinalTranscript,
}: UseVietnameseSpeechRecognitionOptions) {
  const [state, setState] = useState<SpeechState>('idle')
  const [message, setMessage] = useState('')
  const [hasError, setHasError] = useState(false)
  const recognition = useRef<BrowserSpeechRecognition | null>(null)
  const recognitionOrigin = useRef<string | null>(null)
  const currentConversationId = useRef(conversationId)
  const finalTranscriptHandler = useRef(onFinalTranscript)
  const isCancelling = useRef(false)
  const isMounted = useRef(true)

  const cancelRecognition = useCallback(() => {
    const activeRecognition = recognition.current
    recognition.current = null
    recognitionOrigin.current = null
    isCancelling.current = true
    activeRecognition?.abort()

    if (isMounted.current) {
      setState('idle')
      setMessage('')
      setHasError(false)
    }
  }, [])

  useLayoutEffect(() => {
    finalTranscriptHandler.current = onFinalTranscript
  }, [onFinalTranscript])

  useLayoutEffect(() => {
    currentConversationId.current = conversationId
    if (recognitionOrigin.current && recognitionOrigin.current !== conversationId) {
      cancelRecognition()
    }
  }, [cancelRecognition, conversationId])

  useEffect(() => {
    if (disabled && recognition.current) cancelRecognition()
  }, [cancelRecognition, disabled])

  useEffect(() => {
    isMounted.current = true
    return () => {
      isMounted.current = false
      recognitionOrigin.current = null
      recognition.current?.abort()
      recognition.current = null
    }
  }, [])

  function startRecognition() {
    if (disabled || recognition.current) return

    const speechWindow = window as SpeechRecognitionWindow
    const RecognitionConstructor = speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition
    if (!RecognitionConstructor) {
      setHasError(true)
      setMessage(UNSUPPORTED_MESSAGE)
      return
    }

    const nextRecognition = new RecognitionConstructor()
    const originId = conversationId
    let recognitionHadError = false
    nextRecognition.lang = 'vi-VN'
    nextRecognition.continuous = true
    nextRecognition.interimResults = true
    isCancelling.current = false

    nextRecognition.onresult = (event) => {
      if (
        recognitionOrigin.current !== originId ||
        currentConversationId.current !== originId
      ) return

      let finalTranscript = ''
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index]
        if (result.isFinal) finalTranscript += result[0]?.transcript ?? ''
      }

      const normalizedTranscript = finalTranscript.trim()
      if (normalizedTranscript) {
        finalTranscriptHandler.current(originId, normalizedTranscript)
      }
    }

    nextRecognition.onerror = (event) => {
      if (isCancelling.current || event.error === 'aborted') return

      recognitionHadError = true
      recognition.current = null
      recognitionOrigin.current = null
      if (!isMounted.current) return

      const permissionDenied = event.error === 'not-allowed' || event.error === 'service-not-allowed'
      setState('idle')
      setHasError(true)
      setMessage(permissionDenied ? PERMISSION_MESSAGE : RECOGNITION_ERROR_MESSAGE)
    }

    nextRecognition.onend = () => {
      if (recognition.current === nextRecognition) recognition.current = null
      if (recognitionOrigin.current === originId) recognitionOrigin.current = null
      if (!isMounted.current) return

      setState('idle')
      if (!recognitionHadError && !isCancelling.current) setMessage('')
      isCancelling.current = false
    }

    recognition.current = nextRecognition
    recognitionOrigin.current = originId
    setHasError(false)
    setMessage('Đang nghe…')
    setState('listening')

    try {
      nextRecognition.start()
    } catch {
      recognition.current = null
      recognitionOrigin.current = null
      setState('idle')
      setHasError(true)
      setMessage(RECOGNITION_ERROR_MESSAGE)
    }
  }

  function stopRecognition() {
    if (!recognition.current || state !== 'listening') return

    setState('stopping')
    setMessage('Đang dừng nghe…')
    recognition.current.stop()
  }

  function toggleRecognition() {
    if (state === 'listening') {
      stopRecognition()
    } else if (state === 'idle') {
      startRecognition()
    }
  }

  return {
    state,
    message,
    hasError,
    toggleRecognition,
    cancelRecognition,
  }
}

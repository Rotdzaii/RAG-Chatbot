import type { QuestionSource } from '../api'

type SourceLocator = Pick<QuestionSource, 'chunk_index' | 'page_start' | 'page_end'>

export function formatSourceLocator(source: SourceLocator) {
  if (source.page_start == null || source.page_end == null) {
    return `Đoạn ${source.chunk_index}`
  }
  if (source.page_start === source.page_end) {
    return `Trang ${source.page_start}`
  }
  return `Trang ${source.page_start}–${source.page_end}`
}

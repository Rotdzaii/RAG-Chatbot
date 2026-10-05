import type { QuestionSource } from '../api'

export type DocumentSources = {
  documentId: string
  filename: string
  sources: QuestionSource[]
}

export function groupCitedSources(answer: string, sources: QuestionSource[]): DocumentSources[] {
  const citedNumbers = new Set<number>()
  for (const match of answer.matchAll(/\[(\d+(?:\s*[,;]\s*\d+)*)\](?!\()/g)) {
    for (const number of match[1].split(/\s*[,;]\s*/)) {
      citedNumbers.add(Number(number))
    }
  }

  const groups = new Map<string, DocumentSources>()
  for (const source of sources) {
    if (!citedNumbers.has(source.citation)) continue
    let group = groups.get(source.document_id)
    if (!group) {
      group = { documentId: source.document_id, filename: source.filename, sources: [] }
      groups.set(source.document_id, group)
    }
    if (!group.sources.some((item) => item.citation === source.citation)) {
      group.sources.push(source)
    }
  }
  return [...groups.values()]
}

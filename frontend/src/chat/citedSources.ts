import type { QuestionSource } from '../api'

export type DocumentSources = {
  documentId: string
  filename: string
  sources: QuestionSource[]
}

export const citationMarkers = /\[(\d+(?:\s*[,;]\s*\d+)*)\](?!\()/g

export function groupCitedSources(answer: string, sources: QuestionSource[]): DocumentSources[] {
  const citedNumbers = new Set<number>()
  for (const match of answer.matchAll(citationMarkers)) {
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

export function toWebsiteReference(source: QuestionSource) {
  if (source.source_file_version_id) return null
  // Some older saved citations placed the URL in filename.
  const candidate = source.source_url?.trim() || source.filename.trim()
  if (!/^https?:\/\//i.test(candidate)) return null

  try {
    const parsedUrl = new URL(candidate)
    if (parsedUrl.protocol !== 'http:' && parsedUrl.protocol !== 'https:') return null

    parsedUrl.hash = ''
    parsedUrl.searchParams.sort()
    if (parsedUrl.pathname.length > 1) {
      parsedUrl.pathname = parsedUrl.pathname.replace(/\/+$/, '')
    }

    return {
      url: parsedUrl.toString(),
      hostname: parsedUrl.hostname.replace(/^www\./i, ''),
      displayUrl: `${parsedUrl.hostname}${parsedUrl.pathname === '/' ? '' : parsedUrl.pathname}${parsedUrl.search}`,
    }
  } catch {
    return null
  }
}

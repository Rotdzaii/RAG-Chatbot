import type { ReactNode } from 'react'
import type { QuestionSource } from '../api'
import { toWebsiteReference } from './citedSources'

type CitationLinkProps = {
  source: QuestionSource
  onOpenFile: (source: QuestionSource) => void
  children: ReactNode
}

export function CitationLink({ source, onOpenFile, children }: CitationLinkProps) {
  const label = `Mở trích dẫn ${source.citation} · ${source.filename}`
  if (source.source_file_version_id) {
    return <button className="citation-link" type="button" title={label} aria-label={label}
      onClick={() => onOpenFile(source)}>{children}</button>
  }

  const website = toWebsiteReference(source)
  if (website) {
    return <a className="citation-link" href={website.url} target="_blank" rel="noopener noreferrer"
      title={label} aria-label={label}>{children}</a>
  }

  return <span title="Chưa lưu file gốc cho trích dẫn này.">{children}</span>
}

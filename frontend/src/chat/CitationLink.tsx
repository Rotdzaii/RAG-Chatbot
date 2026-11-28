import type { ReactNode } from 'react'
import type { QuestionSource } from '../api'
import { toWebsiteReference } from './citedSources'

type CitationLinkProps = {
  source: QuestionSource
  onOpenFile: (source: QuestionSource) => void
  className?: string
  label?: string
  children?: ReactNode
}

export function CitationLink({ source, onOpenFile, className = 'citation-link', label, children }: CitationLinkProps) {
  const website = toWebsiteReference(source)
  const name = source.filename.trim() || website?.hostname || `Nguồn ${source.citation}`
  const accessibleLabel = label ?? `Mở trích dẫn ${source.citation} · ${name}`
  const content = children ?? `[${source.citation}]`
  if (website) {
    return <a className={className} href={website.url} target="_blank" rel="noopener noreferrer"
      title={name} aria-label={accessibleLabel}>{content}</a>
  }
  return <button className={className} type="button" aria-haspopup="dialog" aria-label={accessibleLabel}
    title={name} onClick={() => onOpenFile(source)}>{content}</button>
}

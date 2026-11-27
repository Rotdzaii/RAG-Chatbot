import type { ReactNode } from 'react'
import type { QuestionSource } from '../api'
import { SourceFileIcon } from '../SourceFileIcon'
import { sourceFileKind } from '../downloadFile'
import { toWebsiteReference } from './citedSources'

type CitationLinkProps = {
  source: QuestionSource
  onOpenFile: (source: QuestionSource) => void
  children?: ReactNode
}

export function CitationLink({ source, onOpenFile, children }: CitationLinkProps) {
  const website = toWebsiteReference(source)
  const name = source.filename.trim() || website?.hostname || `Nguồn ${source.citation}`
  const kind = website ? 'Web' : sourceFileKind(name, source.mime_type)
  const label = `Mở trích dẫn ${source.citation} · ${name}`
  const content = children ?? <><SourceFileIcon kind={kind} /><span className="citation-link__name">{name}</span></>
  if (website) {
    return <a className="citation-link" href={website.url} target="_blank" rel="noopener noreferrer"
      title={name} aria-label={label}>{content}</a>
  }
  if (children && !source.source_file_version_id) {
    return <span title="Chưa lưu tệp gốc cho trích dẫn này.">{children}</span>
  }
  return <button className="citation-link" type="button" aria-haspopup="dialog" aria-label={label}
    title={name} onClick={() => onOpenFile(source)}>{content}</button>
}

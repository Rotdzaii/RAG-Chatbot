import { useId, useLayoutEffect, useRef, useState } from 'react'
import { gsap } from 'gsap'
import type { QuestionSource } from '../api'
import { sourceFileKind } from '../downloadFile'
import { SourceFileIcon } from '../SourceFileIcon'
import { CitationLink } from './CitationLink'
import { groupCitedSources, toWebsiteReference, type DocumentSources } from './citedSources'
import { formatSourceLocator } from './sourceLocator'

type AnswerSourcesProps = {
  answer: string
  sources: QuestionSource[]
  onOpenFile: (source: QuestionSource) => void
}

function AnswerSourceRow({ group, onOpenFile }: {
  group: DocumentSources
  onOpenFile: AnswerSourcesProps['onOpenFile']
}) {
  const [first, ...rest] = group.sources
  const website = toWebsiteReference(first)
  const kind = website ? 'Web' : sourceFileKind(first.filename, first.mime_type)
  const filename = group.filename.trim()
  const shortFilename = website && /^https?:\/\//i.test(filename)
    ? website.hostname
    : filename.replace(/\.(?:pdf|txt)$/i, '').replace(/_+/g, ' ').trim()
  const sourceTitle = typeof first.title === 'string' ? first.title.trim() : ''
  const title = sourceTitle || shortFilename || website?.hostname || `Nguồn ${first.citation}`
  const canOpen = Boolean(website || first.source_file_version_id)
  const hasPage = kind === 'PDF' && first.page_start != null
  const location = hasPage ? `${kind} · ${formatSourceLocator(first)}` : kind
  const metadata = canOpen ? location : 'Chưa có tệp gốc để xem'
  const starts = new Set([first.page_start])
  const additionalPages = kind === 'PDF' && first.source_file_version_id ? rest.filter(source => {
    if (source.page_start == null || starts.has(source.page_start)) return false
    starts.add(source.page_start)
    return true
  }) : []

  const row = <>
    <SourceFileIcon kind={kind} />
    <span className="answer-source-details">
      <span className="answer-source-title">
        <span className="citation-number">[{first.citation}]</span>{' '}{title}
      </span>
      <span className="answer-source-meta">{metadata}</span>
    </span>
    {canOpen && <svg className="answer-source-arrow" viewBox="0 0 16 16" aria-hidden="true">
      <path d="m6 3.5 4.5 4.5L6 12.5" />
    </svg>}
  </>

  return <li>
    {canOpen
      ? <CitationLink className="answer-source-row" source={first} onOpenFile={onOpenFile}
        label={`[${first.citation}] ${title} · ${metadata}`}>{row}</CitationLink>
      : <div className="answer-source-row">{row}</div>}
    {additionalPages.length > 0 && <div className="answer-source-pages">
      {additionalPages.map(source => <CitationLink key={source.citation} source={source} onOpenFile={onOpenFile}
        label={`[${source.citation}] ${formatSourceLocator(source)} · ${title}`}>
        <span className="citation-number">[{source.citation}]</span>{' '}{formatSourceLocator(source)}
      </CitationLink>)}
    </div>}
  </li>
}

export function AnswerSources({ answer, sources, onOpenFile }: AnswerSourcesProps) {
  const [open, setOpen] = useState(false)
  const listId = useId()
  const toggle = useRef<HTMLButtonElement>(null)
  const list = useRef<HTMLUListElement>(null)
  const groups = groupCitedSources(answer, sources)
  const hasSources = groups.length > 0

  useLayoutEffect(() => {
    const element = list.current
    if (!open || !hasSources || !element) return
    const motion = gsap.matchMedia()
    motion.add('(prefers-reduced-motion: no-preference)', () => {
      gsap.from(element, { opacity: 0, y: -4, duration: 0.16, ease: 'power1.out' })
    })
    return () => motion.revert()
  }, [open, hasSources])

  if (!hasSources) return null

  return <div className="answer-sources" onKeyDown={event => {
    if (event.key !== 'Escape' || !open) return
    event.stopPropagation()
    setOpen(false)
    toggle.current?.focus()
  }}>
    <button type="button" className="answer-sources-toggle" ref={toggle}
      aria-expanded={open} aria-controls={listId} onClick={() => setOpen(value => !value)}>
      Xem {groups.length} nguồn
      <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 6 4.5 4.5L12.5 6" /></svg>
    </button>
    <ul className="answer-source-list" ref={list} id={listId} hidden={!open} aria-label="Nguồn của câu trả lời">
      {open && groups.map(group => <AnswerSourceRow
        key={`${group.documentId}:${group.sources[0].source_file_version_id ?? ''}`}
        group={group} onOpenFile={onOpenFile} />)}
    </ul>
  </div>
}

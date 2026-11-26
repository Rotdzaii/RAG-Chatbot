import { useMemo } from 'react'
import type { Element, Root, Text } from 'hast'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { QuestionSource } from '../api'
import { CitationLink } from './CitationLink'
import { citationMarkers } from './citedSources'

function markCitationText(parent: Root | Element) {
  for (let index = 0; index < parent.children.length; index += 1) {
    const node = parent.children[index]
    if (node.type === 'element' && !['a', 'code', 'pre'].includes(node.tagName)) {
      markCitationText(node)
    }
    if (node.type !== 'text') continue

    const parts: (Text | Element)[] = []
    let offset = 0
    for (const match of node.value.matchAll(citationMarkers)) {
      parts.push({ type: 'text', value: node.value.slice(offset, match.index) })
      parts.push({
        type: 'element', tagName: 'span', properties: { dataCitationMarkers: match[1] },
        children: [{ type: 'text', value: match[0] }],
      })
      offset = match.index + match[0].length
    }

    if (offset === 0) continue
    parts.push({ type: 'text', value: node.value.slice(offset) })
    parent.children.splice(index, 1, ...parts)
    index += parts.length - 1
  }
}

function rehypeCitations() {
  return markCitationText
}

type AnswerMarkdownProps = {
  answer: string
  sources: QuestionSource[]
  onOpenFile: (source: QuestionSource) => void
}

export default function AnswerMarkdown({ answer, sources, onOpenFile }: AnswerMarkdownProps) {
  const components = useMemo<Components>(() => {
    const byNumber = new Map(sources.map(source => [source.citation, source]))

    function renderCitation(number: string, label: string) {
      const source = byNumber.get(Number(number))
      return source ? <CitationLink source={source} onOpenFile={onOpenFile}>{label}</CitationLink> : label
    }

    return {
      span: ({ node, children, ...props }) => {
        const numbers = node?.properties.dataCitationMarkers
        if (typeof numbers !== 'string') return <span {...props}>{children}</span>
        const parts = numbers.split(/(\s*[,;]\s*)/)
        if (parts.length === 1) return renderCitation(numbers, `[${numbers}]`)
        return <>[{parts.map((part, index) => (
          <span key={index}>{index % 2 === 0 ? renderCitation(part, part) : part}</span>
        ))}]</>
      },
    }
  }, [sources, onOpenFile])

  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeCitations]} components={components} skipHtml>
      {answer.replace(/<br\s*\/?\s*>/gi, '  \n')}
    </ReactMarkdown>
  )
}

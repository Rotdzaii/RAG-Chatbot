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
    if (node.type === 'raw' && /^<br\s*\/?\s*>$/i.test(node.value)) {
      parent.children[index] = { type: 'element', tagName: 'br', properties: {}, children: [] }
    }
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

    return {
      span: ({ node, children, ...props }) => {
        const numbers = node?.properties.dataCitationMarkers
        if (typeof numbers !== 'string') return <span {...props}>{children}</span>
        return [...new Set(numbers.split(/\s*[,;]\s*/).map(Number))].map(number => {
          const source = byNumber.get(number)
          return source ? <CitationLink key={number} source={source} onOpenFile={onOpenFile} /> : `[${number}]`
        })
      },
    }
  }, [sources, onOpenFile])

  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeCitations]} components={components} skipHtml>
      {answer}
    </ReactMarkdown>
  )
}

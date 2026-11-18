import { useMemo } from 'react'
import type { GroundedResult } from '../api'

// Accept static widget markup as a unit so a rejected widget does not leave
// the grounded result visible by itself. Shadow DOM scopes the provider's CSS.
const widgetTags = new Set([
  'a', 'b', 'br', 'div', 'em', 'p', 'span', 'strong', 'style',
  'svg', 'g', 'path', 'circle', 'rect', 'line', 'polyline', 'polygon', 'title',
])
const widgetAttributes = new Set([
  'class', 'id', 'role', 'style', 'type', 'title', 'aria-hidden', 'aria-label', 'dir',
  'xmlns', 'width', 'height', 'viewbox', 'd', 'fill', 'fill-rule', 'clip-rule', 'stroke',
  'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'cx', 'cy', 'r', 'rx', 'ry',
  'x', 'y', 'x1', 'x2', 'y1', 'y2', 'points', 'transform', 'focusable',
])
const resourceStyles = /\\|@import|url\s*\(|image-set\s*\(|expression\s*\(/i

function safeUrl(value: string) {
  if (!/^https?:\/\//i.test(value) || /[\s\\]/.test(value)) return null
  try {
    const url = new URL(value)
    return url.hostname && !url.username && !url.password ? url : null
  } catch {
    return null
  }
}

function readWidget(html: string): DocumentFragment | null {
  const template = document.createElement('template')
  template.innerHTML = html
  let hasSearchLink = false
  for (const element of template.content.querySelectorAll('*')) {
    const tag = element.localName.toLowerCase()
    if (!widgetTags.has(tag)) return null
    if (tag === 'style' && resourceStyles.test(element.textContent ?? '')) return null
    for (const attr of element.attributes) {
      const name = attr.name.toLowerCase()
      if (tag === 'a' && name === 'href') {
        const url = safeUrl(attr.value)
        if (!url || url.origin !== 'https://www.google.com' || url.pathname !== '/search') return null
        hasSearchLink = true
      } else if (tag === 'a' && name === 'target') {
        if (!['_self', '_blank'].includes(attr.value)) return null
      } else if (!(tag === 'a' && name === 'rel')
        && (!widgetAttributes.has(name) || resourceStyles.test(attr.value))) {
        return null
      }
    }
  }
  return hasSearchLink ? template.content : null
}

export function GoogleGrounding({ result }: { result: GroundedResult }) {
  const widget = useMemo(() => readWidget(result.search_suggestions_html), [result.search_suggestions_html])
  const sources = result.sources.filter(source => safeUrl(source.url))
  if (!widget || sources.length === 0) {
    return <p>Hiện chưa thể hiển thị thông tin cập nhật kèm nguồn xác minh.</p>
  }

  return (
    <section aria-label="Thông tin cập nhật từ Google Search" className="answer-sources">
      <h2>Thông tin cập nhật từ Google Search</h2>
      <p className="message-text" style={{ whiteSpace: 'pre-wrap' }}>{result.text}</p>
      <ul className="source-list" aria-label="Nguồn web từ Google Search">
        {sources.map(source => (
          <li key={source.url}>
            <a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a>
          </li>
        ))}
      </ul>
      <div aria-label="Gợi ý tìm kiếm từ Google" ref={element => {
        if (element) {
          const shadow = element.shadowRoot ?? element.attachShadow({ mode: 'open' })
          shadow.replaceChildren(widget.cloneNode(true))
        }
      }} />
    </section>
  )
}

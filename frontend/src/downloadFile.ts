export function sourceFileKind(filename: string, mime?: string | null): 'PDF' | 'TXT' {
  const type = mime?.split(';')[0].trim().toLowerCase()
  if (type === 'application/pdf') return 'PDF'
  if (type === 'text/plain') return 'TXT'
  return /\.pdf$/i.test(filename) ? 'PDF' : 'TXT'
}

export function downloadFile(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

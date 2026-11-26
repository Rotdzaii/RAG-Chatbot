export function CitationDownloadButton({ filename, disabled, onClick }: {
  filename: string
  disabled: boolean
  onClick: () => void
}) {
  return (
    <button type="button" className="citation-download-button" disabled={disabled}
      aria-label={`Tải tệp gốc · ${filename}`} onClick={onClick}>
      Tải tệp gốc
    </button>
  )
}

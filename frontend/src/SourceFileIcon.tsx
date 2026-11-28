export function SourceFileIcon({ kind }: { kind: 'PDF' | 'TXT' | 'Web' }) {
  return <svg className="source-file-icon" data-kind={kind} viewBox="0 0 20 20" fill="none"
    stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {kind === 'Web' ? <>
      <circle cx="10" cy="10" r="7.5" /><ellipse cx="10" cy="10" rx="3.2" ry="7.5" /><path d="M3 10h14" />
    </> : <>
      <path d="M5 2.5h6l4.5 4.6v10.4H5zM11 2.5v5h4.5" />
      {kind === 'TXT' ? <path d="M7.5 10.7h5.6m-5.6 3h4" />
        : <path d="M7.2 14.3c1.3-1.1 2.4-3.5 2.6-5.1.4 2 1.1 3.3 3 4.2-2-.6-3.9-.4-5.6.9Z" />}
    </>}
  </svg>
}

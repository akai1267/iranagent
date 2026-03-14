import ReactMarkdown from 'react-markdown'

function formatDateTime(value) {
  if (!value) {
    return 'Unknown'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return String(value)
  }
  return date.toLocaleString('en-US', {
    month: 'short',
    day: '2-digit',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
}

export default function CurrentPicture({ snapshot, loading, error }) {
  const stale = Boolean(snapshot?.stale)

  return (
    <section className="current-picture-shell">
      <header className="current-picture-header">
        <span className="overline">CURRENT PICTURE</span>
        <span className="timestamp">Updated {formatDateTime(snapshot?.generated_at)}</span>
      </header>

      <div className="current-picture-meta">
        {snapshot?.source_generated_at ? (
          <span className="timestamp">Source generated {formatDateTime(snapshot.source_generated_at)}</span>
        ) : null}
        {snapshot?.model ? <span className="tag tag-neutral">Model: {String(snapshot.model).toUpperCase()}</span> : null}
        {stale ? <span className="tag tag-watch">STALE</span> : null}
      </div>

      {loading ? <p className="muted-row">Loading current picture…</p> : null}

      {!loading && error?.kind === 'warming' ? <p className="muted-row">{error.message}</p> : null}
      {!loading && error?.kind === 'network' ? <p className="muted-row">{error.message}</p> : null}

      {!loading && snapshot?.content ? (
        <article className="current-picture-body">
          <ReactMarkdown>{snapshot.content}</ReactMarkdown>
        </article>
      ) : null}

      {!loading && snapshot?.source_url ? (
        <div className="current-picture-source-link-wrap">
          <a href={snapshot.source_url} target="_blank" rel="noreferrer" className="current-picture-source-link">
            Source: IranMonitor prompt export
          </a>
        </div>
      ) : null}
    </section>
  )
}

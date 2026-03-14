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

function prettyProvider(provider) {
  if (!provider) {
    return 'unknown'
  }
  return String(provider).replace(/_/g, ' ')
}

function prettyKind(kind) {
  if (!kind) {
    return 'document'
  }
  return String(kind).replace(/_/g, ' ')
}

function statusClass(status) {
  return status === 'ok' ? 'status-pill ok' : 'status-pill down'
}

export default function CurrentPicture({ snapshot, status, loading, error, stale }) {
  const meta = snapshot?.meta || {}
  const sources = Array.isArray(snapshot?.sources) ? snapshot.sources : []
  const providerStatus = status?.provider_status || {}

  return (
    <section className="current-picture-shell">
      <header className="current-picture-header">
        <span className="overline">CURRENT PICTURE</span>
        <span className="timestamp">Updated {formatDateTime(snapshot?.generated_at)}</span>
      </header>

      <div className="current-picture-meta">
        <span className="tag tag-neutral">Anchor: {String(meta.primary_anchor_cycle || 'unknown').toUpperCase()}</span>
        <span className="timestamp">Anchor published {formatDateTime(meta.primary_anchor_published_at)}</span>
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

      <section className="current-picture-status">
        <div className="section-rule">Provider Health</div>
        <div className="current-picture-provider-grid">
          {Object.entries(providerStatus).map(([provider, providerState]) => (
            <div className="current-picture-provider-row" key={provider}>
              <span className="current-picture-provider-name">{prettyProvider(provider)}</span>
              <span className={statusClass(providerState)}>{String(providerState || 'unknown').toUpperCase()}</span>
            </div>
          ))}
          {Object.keys(providerStatus).length === 0 ? <p className="muted-row">Provider health unavailable.</p> : null}
        </div>
      </section>

      <section className="current-picture-sources">
        <div className="section-rule">Sources</div>
        {sources.length === 0 ? (
          <p className="muted-row">No source references yet.</p>
        ) : (
          <ul className="current-picture-source-list">
            {sources.map((source) => (
              <li className="current-picture-source-row" key={source.id}>
                <a href={source.url} target="_blank" rel="noreferrer" className="current-picture-source-link">
                  {source.title}
                </a>
                <div className="current-picture-source-meta">
                  <span>{prettyProvider(source.provider)}</span>
                  <span>{prettyKind(source.doc_kind)}</span>
                  <span>{formatDateTime(source.published_at)}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </section>
  )
}

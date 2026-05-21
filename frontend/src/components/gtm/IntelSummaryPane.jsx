import ReactMarkdown from 'react-markdown'

function formatDateTime(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return 'Unknown'
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

export default function IntelSummaryPane({ snapshot, loading, error }) {
  if (loading) {
    return (
      <section className="left-pane intel-summary-pane">
        <p className="muted-row">Loading executive read...</p>
      </section>
    )
  }

  if (error) {
    return (
      <section className="left-pane intel-summary-pane">
        <p className="muted-row">{error.message}</p>
      </section>
    )
  }

  return (
    <section className="left-pane intel-summary-pane">
      <header className="pane-header">
        <div>
          <div className="overline">{snapshot.windowLabel.toUpperCase()}</div>
          <h2 className="pane-title">Executive Read</h2>
        </div>
        <div className="pane-header-meta">
          <span className="timestamp">Updated {formatDateTime(snapshot.generatedAt)}</span>
          <span className="timestamp">{snapshot.refreshCadenceLabel}</span>
          <span className="tag tag-neutral">{snapshot.icpLabel}</span>
        </div>
      </header>

      <section className="topline-card card">
        <div className="overline">TOPLINE</div>
        <p className="topline-text">{snapshot.executiveRead.topline}</p>
      </section>

      <div className="signal-meta-row">
        <span className="tag tag-neutral">Sources: {snapshot.sourceCount}</span>
        <span className="tag tag-neutral">Confidence: {String(snapshot.confidence).toUpperCase()}</span>
        <span className="tag tag-neutral">Temperature: {String(snapshot.marketTemperature).toUpperCase()}</span>
        {snapshot.categoryTags.map((tag) => (
          <span key={tag} className="tag tag-neutral">
            {tag}
          </span>
        ))}
      </div>

      {snapshot.executiveRead.sinceLastPass?.length ? (
        <section className="card shifts-card">
          <div className="overline">SINCE LAST PASS</div>
          <ul className="drivers-list">
            {snapshot.executiveRead.sinceLastPass.map((item) => (
              <li key={item.label}>
                <strong>{item.label}:</strong> {item.note}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <article className="current-picture-body card intel-summary-body">
        <ReactMarkdown>{snapshot.executiveRead.markdown}</ReactMarkdown>
      </article>

      <section className="card drivers-card">
        <div className="overline">WHAT IS DRIVING THIS</div>
        <ul className="drivers-list">
          {snapshot.executiveRead.drivers.map((driver) => (
            <li key={driver}>{driver}</li>
          ))}
        </ul>
      </section>
    </section>
  )
}

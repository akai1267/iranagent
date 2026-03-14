function formatDate() {
  const now = new Date()
  return now.toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

export default function Header({ connected }) {
  return (
    <header className="header-shell">
      <div className="wordmark">Iran War Monitor AI Agentic Analyst</div>
      <div className="header-meta">
        <span className="live-dot" />
        <span className="timestamp">{connected ? 'LIVE' : 'RECONNECTING'}</span>
        <span className="timestamp">Vol. I · {formatDate()}</span>
      </div>
    </header>
  )
}

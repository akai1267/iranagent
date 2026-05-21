function formatDate() {
  const now = new Date()
  return now.toLocaleDateString('en-US', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

export default function Header() {
  return (
    <header className="header-shell">
      <div className="wordmark">GTM Leads Research Analyst</div>
      <div className="header-meta">
        <span className="timestamp">DEMO</span>
        <span className="timestamp">Past 7 days</span>
        <span className="timestamp">Vol. I · {formatDate()}</span>
      </div>
    </header>
  )
}

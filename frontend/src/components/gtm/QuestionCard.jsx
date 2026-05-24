function statusClass(status) {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'active') {
    return 'status-chip status-chip-active'
  }
  if (normalized === 'verifying') {
    return 'status-chip status-chip-verifying'
  }
  return 'status-chip status-chip-watch'
}

function statusLabel(status) {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'active') {
    return 'HOT'
  }
  if (normalized === 'verifying') {
    return 'CHECKING'
  }
  return 'ON RADAR'
}

export default function QuestionCard({ question }) {
  return (
    <article className="workspace-card question-card">
      <div className="workspace-card-header">
        <h3 className="workspace-card-title">{question.title}</h3>
        <span className={statusClass(question.status)}>{statusLabel(question.status)}</span>
      </div>
      <p className="workspace-card-copy">{question.whyItMatters}</p>
      <div className="signal-chip-row">
        {question.signalRefs.map((signal) => (
          <span key={signal} className="signal-chip">
            {signal}
          </span>
        ))}
      </div>
    </article>
  )
}

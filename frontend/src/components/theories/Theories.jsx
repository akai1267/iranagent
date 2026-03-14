import ReactMarkdown from 'react-markdown'

function relativeTime(isoTimestamp) {
  if (!isoTimestamp) {
    return 'Unknown'
  }

  const date = new Date(isoTimestamp)
  if (Number.isNaN(date.getTime())) {
    return isoTimestamp
  }

  const elapsed = Math.max(0, Date.now() - date.getTime())
  const minutes = Math.floor(elapsed / 60000)
  if (minutes < 60) {
    return `${minutes}m ago`
  }
  const hours = Math.floor(minutes / 60)
  if (hours < 24) {
    return `${hours}h ago`
  }
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export default function Theories({ content, updatedAt, justUpdated }) {
  const blocks = String(content || '')
    .split(/\n\n+/)
    .map((block) => block.trim())
    .filter(Boolean)

  const firstBlock = blocks[0] || ''
  const remaining = blocks.slice(1).join('\n\n')

  return (
    <section className={`theories-shell ${justUpdated ? 'theories-updated' : ''}`}>
      <header className="theories-header">
        <span className="overline">WORKING THEORIES</span>
        <span className="timestamp">Last updated {relativeTime(updatedAt)}</span>
      </header>

      {firstBlock ? <p className="lede-quote">{firstBlock}</p> : null}

      {remaining ? (
        <div className="theories-body">
          <ReactMarkdown>{remaining}</ReactMarkdown>
        </div>
      ) : !firstBlock ? (
        <p className="muted-row">No working theories yet.</p>
      ) : null}
    </section>
  )
}

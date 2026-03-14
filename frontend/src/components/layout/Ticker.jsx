export default function Ticker({ show, headline, onClose }) {
  if (!show || !headline) {
    return null
  }

  const text = `[BREAKING] ${headline}`

  return (
    <section className="ticker" role="status" aria-live="polite">
      <span className="ticker-label">BREAKING</span>
      <div className="ticker-track-wrap">
        <div className="ticker-track">
          <span>{text}</span>
          <span>{text}</span>
        </div>
      </div>
      <button type="button" className="ticker-close" onClick={onClose} aria-label="Dismiss breaking ticker">
        ×
      </button>
    </section>
  )
}

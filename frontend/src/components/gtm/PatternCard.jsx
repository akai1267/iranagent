export default function PatternCard({ pattern }) {
  return (
    <article className="workspace-card pattern-card">
      <h3 className="workspace-card-title">{pattern.title}</h3>
      <p className="workspace-card-copy">{pattern.summary}</p>
      <p className="workspace-card-meta"><strong>Why now:</strong> {pattern.whyNow}</p>
      <p className="workspace-card-meta"><strong>Who it fits:</strong> {pattern.archetype}</p>
    </article>
  )
}

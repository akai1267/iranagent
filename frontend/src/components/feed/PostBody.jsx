export default function PostBody({ content }) {
  const paragraphs = String(content || '')
    .split(/\n\n+/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean)

  return (
    <div className="post-body">
      {paragraphs.map((paragraph, index) => (
        <p key={index}>{paragraph}</p>
      ))}
    </div>
  )
}

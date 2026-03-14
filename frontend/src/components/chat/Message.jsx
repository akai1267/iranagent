import ReactMarkdown from 'react-markdown'

function extractPostId(href) {
  const match = String(href || '').match(/\/posts\/([^/\s]+)/)
  return match ? match[1] : null
}

export default function Message({ message, onCitation }) {
  if (message.role === 'user') {
    return (
      <div className="chat-line user-line">
        <span className="timestamp">You:</span>
        <span className="user-message">{message.content}</span>
      </div>
    )
  }

  return (
    <div className="chat-line assistant-line">
      <ReactMarkdown
        components={{
          a: ({ href, children }) => {
            const postId = extractPostId(href)
            if (postId) {
              return (
                <button
                  type="button"
                  className="citation-link"
                  onClick={() => onCitation(postId)}
                  title={`Open post ${postId}`}
                >
                  {children}
                </button>
              )
            }
            return (
              <a href={href} className="citation-link" target="_blank" rel="noreferrer">
                {children}
              </a>
            )
          },
        }}
      >
        {message.content}
      </ReactMarkdown>
    </div>
  )
}

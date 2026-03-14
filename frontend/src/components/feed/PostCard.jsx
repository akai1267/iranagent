import { useMemo, useState } from 'react'

import PostBody from './PostBody'
import { getCardBorderColor, getTagClass } from '../../lib/tagColors'

function formatTimestamp(value) {
  if (!value) {
    return 'Unknown'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString([], {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
}

function previewText(content) {
  const chunks = String(content || '')
    .replace(/\s+/g, ' ')
    .split('. ')
    .filter(Boolean)

  return `${chunks.slice(0, 4).join('. ')}${chunks.length > 4 ? '...' : ''}`
}

export default function PostCard({
  post,
  isNew,
  isSuperseded,
  supersededById,
  supersedesTimestamp,
  highlighted,
  onJumpToPost,
}) {
  const [expanded, setExpanded] = useState(false)

  const tags = useMemo(
    () =>
      String(post.tags || '')
        .split(',')
        .map((tag) => tag.trim())
        .filter(Boolean),
    [post.tags],
  )

  const borderColor = getCardBorderColor(tags)

  return (
    <article
      id={`post-${post.id}`}
      className={`card post-card ${isNew ? 'new' : ''} ${highlighted ? 'post-highlight' : ''}`}
      style={borderColor ? { borderTop: `3px solid ${borderColor}` } : undefined}
    >
      <div className="post-meta-row">
        <div className="post-tags">
          {tags.length > 0 ? (
            tags.map((tag) => (
              <span key={tag} className={`tag ${getTagClass(tag)}`}>
                {tag}
              </span>
            ))
          ) : (
            <span className="tag tag-neutral">analysis</span>
          )}

          {isSuperseded && <span className="tag tag-watch">updated</span>}
        </div>

        <span className="timestamp">{formatTimestamp(post.timestamp)}</span>
      </div>

      <h3 className={`post-title ${isSuperseded ? 'post-superseded' : ''}`}>{post.title}</h3>

      {post.supersedes && (
        <div className="timestamp supersedes-note">
          Updates analysis from {supersedesTimestamp ? formatTimestamp(supersedesTimestamp) : 'a prior post'}
        </div>
      )}

      {expanded ? (
        <PostBody content={post.content} />
      ) : (
        <div className="post-preview-wrap">
          <p className="post-body">{previewText(post.content)}</p>
          <div className="post-preview-fade" />
        </div>
      )}

      <div className="post-footer-row">
        <button type="button" className="tiny-btn" onClick={() => setExpanded((value) => !value)}>
          {expanded ? 'Read less ▴' : 'Read more ▾'}
        </button>

        {post.supersedes && <span className="timestamp">● supersedes prior analysis</span>}

        {isSuperseded && supersededById && (
          <button type="button" className="tiny-btn" onClick={() => onJumpToPost?.(supersededById)}>
            → see updated analysis
          </button>
        )}
      </div>
    </article>
  )
}

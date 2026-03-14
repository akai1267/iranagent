import { useMemo, useState } from 'react'

import OpenQuestions from './OpenQuestions'
import PostCard from './PostCard'

const FILTERS = ['all', 'nuclear', 'proxy', 'diplomatic', 'analysis']

export default function Feed({ posts, newIds, questions, highlightPostId }) {
  const [activeFilter, setActiveFilter] = useState('all')

  const supersededIds = useMemo(() => {
    const result = new Set()
    posts.forEach((post) => {
      if (post.supersedes) {
        result.add(post.supersedes)
      }
    })
    return result
  }, [posts])

  const supersededBy = useMemo(() => {
    const result = new Map()
    posts.forEach((post) => {
      if (post.supersedes) {
        result.set(post.supersedes, post.id)
      }
    })
    return result
  }, [posts])

  const postById = useMemo(() => {
    const result = new Map()
    posts.forEach((post) => result.set(post.id, post))
    return result
  }, [posts])

  const visiblePosts = useMemo(() => {
    if (activeFilter === 'all') {
      return posts
    }
    return posts.filter((post) =>
      String(post.tags || '')
        .toLowerCase()
        .split(',')
        .map((tag) => tag.trim())
        .includes(activeFilter),
    )
  }, [posts, activeFilter])

  return (
    <section className="feed-view">
      <header className="feed-header">
        <div className="overline">ANALYSIS FEED</div>
        <div className="feed-filters">
          {FILTERS.map((filter) => (
            <button
              key={filter}
              type="button"
              className={`tag ${activeFilter === filter ? 'tag-urgent' : 'tag-neutral'}`}
              onClick={() => setActiveFilter(filter)}
            >
              {filter}
            </button>
          ))}
        </div>
        <div className="section-rule">{visiblePosts.length} posts</div>
      </header>

      <OpenQuestions questions={questions} />

      {visiblePosts.length === 0 ? (
        <div className="empty-state">
          <span className="live-dot" /> Researcher is working...
        </div>
      ) : (
        visiblePosts.map((post) => (
          <PostCard
            key={post.id}
            post={post}
            isNew={newIds.has(post.id)}
            isSuperseded={supersededIds.has(post.id)}
            supersededById={supersededBy.get(post.id)}
            supersedesTimestamp={postById.get(post.supersedes || '')?.timestamp || null}
            highlighted={highlightPostId === post.id}
            onJumpToPost={(id) => {
              const target = document.getElementById(`post-${id}`)
              if (target) {
                target.scrollIntoView({ behavior: 'smooth', block: 'center' })
              }
            }}
          />
        ))
      )}
    </section>
  )
}

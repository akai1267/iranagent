import { useEffect, useState } from 'react'

import { API_BASE } from '../lib/api'

export function usePosts() {
  const [posts, setPosts] = useState([])
  const [newIds, setNewIds] = useState(new Set())

  useEffect(() => {
    let mounted = true

    async function fetchPosts() {
      try {
        const response = await window.fetch(`${API_BASE}/posts`)
        if (!response.ok) {
          return
        }
        const data = await response.json()

        if (!mounted) {
          return
        }

        setPosts((previous) => {
          const previousIds = new Set(previous.map((post) => post.id))
          const incoming = data.filter((post) => !previousIds.has(post.id))
          if (incoming.length > 0) {
            const fresh = new Set(incoming.map((post) => post.id))
            setNewIds(fresh)
            window.setTimeout(() => setNewIds(new Set()), 1000)
          }
          return data
        })
      } catch {
        // Ignore transient polling errors.
      }
    }

    fetchPosts()
    const timer = window.setInterval(fetchPosts, 30000)

    return () => {
      mounted = false
      window.clearInterval(timer)
    }
  }, [])

  return { posts, newIds }
}

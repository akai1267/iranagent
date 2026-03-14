import { useEffect, useRef, useState } from 'react'

import { API_BASE } from '../lib/api'

export function useTheories() {
  const [content, setContent] = useState('')
  const [updatedAt, setUpdatedAt] = useState(null)
  const [justUpdated, setJustUpdated] = useState(false)
  const previousContent = useRef('')

  useEffect(() => {
    let mounted = true

    async function fetchTheories() {
      try {
        const response = await window.fetch(`${API_BASE}/working-theories`)
        if (!response.ok) {
          return
        }
        const data = await response.json()
        if (!mounted) {
          return
        }

        if (previousContent.current && previousContent.current !== data.content) {
          setJustUpdated(true)
          window.setTimeout(() => setJustUpdated(false), 1500)
        }

        previousContent.current = data.content || ''
        setContent(data.content || '')
        setUpdatedAt(data.updated_at || null)
      } catch {
        // Ignore transient polling errors.
      }
    }

    fetchTheories()
    const timer = window.setInterval(fetchTheories, 60000)

    return () => {
      mounted = false
      window.clearInterval(timer)
    }
  }, [])

  return { content, updatedAt, justUpdated }
}

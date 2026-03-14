import { useEffect, useState } from 'react'

import { API_BASE } from '../lib/api'

export function useQuestions() {
  const [questions, setQuestions] = useState([])

  useEffect(() => {
    let mounted = true

    async function fetchQuestions() {
      try {
        const response = await window.fetch(`${API_BASE}/questions`)
        if (!response.ok) {
          return
        }
        const data = await response.json()
        if (!mounted) {
          return
        }
        setQuestions(
          [...data].sort((left, right) => Number(right.priority || 0) - Number(left.priority || 0)),
        )
      } catch {
        // Ignore transient polling errors.
      }
    }

    fetchQuestions()
    const timer = window.setInterval(fetchQuestions, 30000)

    return () => {
      mounted = false
      window.clearInterval(timer)
    }
  }, [])

  return { questions }
}

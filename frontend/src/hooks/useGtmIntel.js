import { useEffect, useState } from 'react'

import { gtmIntelMock } from '../data/gtmIntelMock'

export function useGtmIntel() {
  const [snapshot, setSnapshot] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    const timer = window.setTimeout(() => {
      if (cancelled) {
        return
      }
      try {
        setSnapshot(gtmIntelMock)
      } catch (err) {
        setError({
          kind: 'mock-load',
          message: err instanceof Error ? err.message : 'Failed to load demo snapshot.',
        })
      } finally {
        setLoading(false)
      }
    }, 320)

    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [])

  return { snapshot, loading, error }
}

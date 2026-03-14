import { useEffect, useState } from 'react'

import { API_BASE } from '../lib/api'

const SNAPSHOT_POLL_MS = 30000

export function useCurrentPicture() {
  const [snapshot, setSnapshot] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let mounted = true
    const controllers = new Set()

    async function fetchSnapshot() {
      const controller = new AbortController()
      controllers.add(controller)
      try {
        const response = await window.fetch(`${API_BASE}/current-picture/latest`, { signal: controller.signal })
        if (response.status === 404) {
          if (mounted) {
            setSnapshot(null)
            setError({ kind: 'warming', message: 'Current picture is warming up.' })
          }
          return
        }
        if (!response.ok) {
          if (mounted) {
            setError({ kind: 'network', message: 'Current picture temporarily unavailable. Retrying…' })
          }
          return
        }
        const data = await response.json()
        if (mounted) {
          setSnapshot(data)
          setError(null)
        }
      } catch {
        if (mounted) {
          setError({ kind: 'network', message: 'Current picture temporarily unavailable. Retrying…' })
        }
      } finally {
        controllers.delete(controller)
      }
    }

    async function bootstrap() {
      await fetchSnapshot()
      if (mounted) {
        setLoading(false)
      }
    }

    bootstrap()
    const snapshotTimer = window.setInterval(fetchSnapshot, SNAPSHOT_POLL_MS)

    return () => {
      mounted = false
      window.clearInterval(snapshotTimer)
      controllers.forEach((controller) => controller.abort())
      controllers.clear()
    }
  }, [])

  return { snapshot, loading, error }
}

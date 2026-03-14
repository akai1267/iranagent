import { useEffect, useMemo, useState } from 'react'

import { API_BASE } from '../lib/api'

const STATUS_POLL_MS = 30000
const SNAPSHOT_POLL_MS = 90000
const DEFAULT_MAX_STALENESS_SEC = 21600

function readMaxStaleness() {
  const raw = Number(import.meta.env.VITE_CONTEXT_MAX_STALENESS_SEC || DEFAULT_MAX_STALENESS_SEC)
  if (!Number.isFinite(raw)) {
    return DEFAULT_MAX_STALENESS_SEC
  }
  return Math.max(300, Math.floor(raw))
}

export function useCurrentPicture() {
  const [snapshot, setSnapshot] = useState(null)
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const maxStalenessSec = useMemo(() => readMaxStaleness(), [])

  useEffect(() => {
    let mounted = true
    const controllers = new Set()

    async function fetchStatus() {
      const controller = new AbortController()
      controllers.add(controller)
      try {
        const response = await window.fetch(`${API_BASE}/context/status`, { signal: controller.signal })
        if (!response.ok) {
          return
        }
        const data = await response.json()
        if (mounted) {
          setStatus(data)
        }
      } catch {
        // Ignore transient status polling errors.
      } finally {
        controllers.delete(controller)
      }
    }

    async function fetchSnapshot() {
      const controller = new AbortController()
      controllers.add(controller)
      try {
        const response = await window.fetch(`${API_BASE}/context/current-picture`, { signal: controller.signal })
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
      await Promise.all([fetchStatus(), fetchSnapshot()])
      if (mounted) {
        setLoading(false)
      }
    }

    bootstrap()
    const statusTimer = window.setInterval(fetchStatus, STATUS_POLL_MS)
    const snapshotTimer = window.setInterval(fetchSnapshot, SNAPSHOT_POLL_MS)

    return () => {
      mounted = false
      window.clearInterval(statusTimer)
      window.clearInterval(snapshotTimer)
      controllers.forEach((controller) => controller.abort())
      controllers.clear()
    }
  }, [])

  const stale = Boolean(
    status &&
      Number.isFinite(Number(status.current_picture_age_seconds)) &&
      Number(status.current_picture_age_seconds) > maxStalenessSec,
  )

  return { snapshot, status, loading, error, stale, maxStalenessSec }
}

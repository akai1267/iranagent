import { useEffect, useRef, useState } from 'react'

import { API_BASE, WS_URL } from '../lib/api'

export function useObservatory() {
  const [events, setEvents] = useState([])
  const [connected, setConnected] = useState(false)
  const [agentStatus, setAgentStatus] = useState(null)
  const wsRef = useRef(null)
  const reconnectRef = useRef(null)
  const lastSeqRef = useRef(0)

  function extractModelHint(summary) {
    const match = String(summary || '').match(/^\[([^\]]+)\]/)
    return match ? match[1].trim().toLowerCase() : ''
  }

  function normalizeIncomingEvent(event) {
    const seq = Number(event?.seq)
    if (!Number.isFinite(seq) || seq <= 0) {
      return null
    }
    return {
      ...event,
      seq,
      has_detail: Boolean(event?.has_detail),
      resolved: event?.event_type !== 'working',
    }
  }

  function mergeEvents(previous, incoming) {
    const bySeq = new Map()
    previous.forEach((event) => {
      if (Number.isFinite(event?.seq)) {
        bySeq.set(event.seq, event)
      }
    })
    incoming.forEach((event) => {
      if (!Number.isFinite(event?.seq)) {
        return
      }
      const existing = bySeq.get(event.seq)
      bySeq.set(event.seq, existing ? { ...existing, ...event } : event)
    })

    const merged = [...bySeq.values()].sort((a, b) => b.seq - a.seq).slice(0, 500)
    if (merged.length > 0) {
      lastSeqRef.current = Math.max(lastSeqRef.current, merged[0].seq)
    }
    return reconcileDoneRows(merged)
  }

  function resolveDoneEvent(previous, doneEvent) {
    const doneModel = extractModelHint(doneEvent.summary)
    let candidateSeq = null

    previous.forEach((event) => {
      if (event.event_type !== 'working' || event.resolved || event.agent !== doneEvent.agent) {
        return
      }
      if (Number.isFinite(doneEvent.seq) && Number.isFinite(event.seq) && event.seq >= doneEvent.seq) {
        return
      }
      if (doneModel) {
        const workingModel = extractModelHint(event.summary)
        if (workingModel && workingModel !== doneModel) {
          return
        }
      }
      if (!Number.isFinite(event.seq)) {
        return
      }
      if (candidateSeq === null || event.seq > candidateSeq) {
        candidateSeq = event.seq
      }
    })

    if (!Number.isFinite(candidateSeq)) {
      return { matched: false, events: previous }
    }

    return {
      matched: true,
      events: previous.map((event) =>
        event.seq === candidateSeq
          ? {
              ...event,
              resolved: true,
              done_summary: doneEvent.preview || doneEvent.summary || event.done_summary,
            }
          : event,
      ),
    }
  }

  function resolveDoneByEventList(list, doneEvent, usedWorking) {
    const doneModel = extractModelHint(doneEvent.summary)

    for (let i = 0; i < list.length; i += 1) {
      const event = list[i]
      if (event.event_type !== 'working' || event.resolved || event.agent !== doneEvent.agent) {
        continue
      }
      if (usedWorking.has(event.seq)) {
        continue
      }
      if (Number.isFinite(doneEvent.seq) && Number.isFinite(event.seq) && event.seq >= doneEvent.seq) {
        continue
      }
      if (doneModel) {
        const workingModel = extractModelHint(event.summary)
        if (workingModel && workingModel !== doneModel) {
          continue
        }
      }
      usedWorking.add(event.seq)
      return i
    }
    return -1
  }

  function reconcileDoneRows(sortedEvents) {
    if (sortedEvents.length === 0) {
      return sortedEvents
    }

    const rows = sortedEvents.map((event) => ({ ...event }))
    const dropSeq = new Set()
    const usedWorking = new Set()

    for (const doneEvent of rows) {
      if (doneEvent.event_type !== 'done') {
        continue
      }
      const index = resolveDoneByEventList(rows, doneEvent, usedWorking)
      if (index < 0) {
        continue
      }
      const matched = rows[index]
      rows[index] = {
        ...matched,
        resolved: true,
        done_summary: doneEvent.preview || doneEvent.summary || matched.done_summary,
      }
      if (Number.isFinite(doneEvent.seq)) {
        dropSeq.add(doneEvent.seq)
      }
    }

    return rows.filter((event) => !dropSeq.has(event.seq))
  }

  useEffect(() => {
    let cancelled = false

    async function fetchRecentEvents(afterSeq = null) {
      try {
        const params = new URLSearchParams({ limit: '200' })
        if (Number.isFinite(afterSeq) && afterSeq > 0) {
          params.set('after_seq', String(afterSeq))
        }
        const response = await window.fetch(`${API_BASE}/observatory/recent?${params.toString()}`)
        if (!response.ok) {
          return
        }
        const data = await response.json()
        if (!Array.isArray(data) || cancelled) {
          return
        }
        const normalized = data.map(normalizeIncomingEvent).filter(Boolean)
        if (normalized.length === 0) {
          return
        }
        setEvents((previous) => mergeEvents(previous, normalized))
      } catch {
        // Ignore transient polling errors.
      }
    }

    async function fetchHealth() {
      try {
        const response = await window.fetch(`${API_BASE}/health`)
        if (!response.ok) {
          return
        }
        const data = await response.json()
        if (!cancelled && data && typeof data.agents === 'object') {
          setAgentStatus(data.agents)
        }
      } catch {
        // Ignore transient polling errors.
      }
    }

    function connect() {
      wsRef.current = new WebSocket(WS_URL)

      wsRef.current.onopen = () => {
        if (!cancelled) {
          setConnected(true)
          fetchHealth()
          fetchRecentEvents(lastSeqRef.current)
        }
      }

      wsRef.current.onclose = () => {
        if (!cancelled) {
          setConnected(false)
          reconnectRef.current = window.setTimeout(connect, 3000)
        }
      }

      wsRef.current.onmessage = (message) => {
        let event
        try {
          event = JSON.parse(message.data)
        } catch {
          return
        }
        const normalized = normalizeIncomingEvent(event)
        if (!normalized) {
          return
        }

        setEvents((previous) => {
          let updated = previous
          if (normalized.event_type === 'done') {
            const resolved = resolveDoneEvent(previous, normalized)
            updated = resolved.events
            if (resolved.matched) {
              return mergeEvents(updated, [])
            }
          }

          return mergeEvents(updated, [normalized])
        })
      }
    }

    fetchRecentEvents()
    fetchHealth()
    connect()
    const healthTimer = window.setInterval(fetchHealth, 15000)

    return () => {
      cancelled = true
      if (reconnectRef.current) {
        window.clearTimeout(reconnectRef.current)
      }
      window.clearInterval(healthTimer)
      wsRef.current?.close()
    }
  }, [])

  return { events, connected, agentStatus }
}

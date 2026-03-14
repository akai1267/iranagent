import { useEffect, useMemo, useState } from 'react'

import { API_BASE } from '../../lib/api'

const ICONS = {
  working: '⏳',
  done: '✓',
  search: '⟳',
  read: '▤',
  decide: '◈',
  write: '✎',
  interrupt: '⚡',
}

const AGENT_CLASSES = {
  orchestrator: 'agent-orchestrator',
  monitor: 'agent-monitor',
  researcher: 'agent-researcher',
  source_monitor: 'agent-source-monitor',
}

function formatTime(value) {
  if (!value) {
    return '--:--'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '--:--'
  }
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: true })
}

function splitDetail(detail) {
  if (!detail) {
    return { metadata: '', prompt: '', response: '' }
  }

  const text = String(detail)
  const sections = text.split('\n\n')
  if (sections.length === 1) {
    return { metadata: '', prompt: text, response: '' }
  }
  const metadata = sections[0] || ''
  const prompt = sections.slice(1).join('\n\n')
  return { metadata, prompt, response: '' }
}

export default function EventRow({ event }) {
  const [expanded, setExpanded] = useState(false)
  const [detail, setDetail] = useState(event.detail || '')
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const hasDetail = Boolean(event.has_detail || event.detail)
  const unresolvedWorking = event.event_type === 'working' && !event.resolved
  const doneLike = event.event_type === 'done' || (event.event_type === 'working' && event.resolved)

  const icon = unresolvedWorking ? '⏳' : doneLike ? '✓' : ICONS[event.event_type] || '•'
  const agentClass = AGENT_CLASSES[event.agent] || ''

  useEffect(() => {
    setDetail(event.detail || '')
    setDetailError('')
    setDetailLoading(false)
  }, [event.seq, event.detail])

  useEffect(() => {
    if (!expanded || !hasDetail || detail || !event.seq) {
      return
    }

    let cancelled = false
    setDetailLoading(true)
    setDetailError('')

    window
      .fetch(`${API_BASE}/observatory/event/${event.seq}`)
      .then(async (response) => {
        if (!response.ok) {
          throw new Error('Detail request failed')
        }
        return response.json()
      })
      .then((payload) => {
        if (cancelled) {
          return
        }
        setDetail(String(payload?.detail || ''))
      })
      .catch(() => {
        if (!cancelled) {
          setDetailError('Detail unavailable')
        }
      })
      .finally(() => {
        if (!cancelled) {
          setDetailLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [expanded, hasDetail, detail, event.seq])

  const parsed = useMemo(() => splitDetail(detail), [detail])

  return (
    <article
      className={`event-row ${agentClass} ${unresolvedWorking ? 'working-row' : ''} ${hasDetail ? 'event-expandable' : ''}`}
      onClick={() => hasDetail && setExpanded((value) => !value)}
      role={hasDetail ? 'button' : undefined}
      tabIndex={hasDetail ? 0 : undefined}
      onKeyDown={(eventKey) => {
        if (!hasDetail) {
          return
        }
        if (eventKey.key === 'Enter' || eventKey.key === ' ') {
          eventKey.preventDefault()
          setExpanded((value) => !value)
        }
      }}
    >
      <div className="event-row-main">
        <span className="timestamp event-time">{formatTime(event.timestamp)}</span>
        <span className={`event-icon ${doneLike ? 'event-icon-done' : ''}`}>{icon}</span>
        <span className={`event-agent ${agentClass}`}>[{event.agent}]</span>
        <span className="event-summary">{event.summary}</span>
        {hasDetail && <span className="event-expand">{expanded ? '▴' : '▾'}</span>}
      </div>
      {event.preview && !expanded && <div className="event-preview">{event.preview}</div>}

      {hasDetail && (
        <div className={`event-expanded ${expanded ? 'open' : ''}`}>
          {detailLoading && <div className="event-expanded-meta">Loading detail...</div>}
          {!detailLoading && detailError && <div className="event-expanded-meta">{detailError}</div>}
          {!detailLoading && !detailError && parsed.metadata && <div className="event-expanded-meta">{parsed.metadata}</div>}
          {!detailLoading && !detailError && parsed.prompt && <div className="event-expanded-block">{parsed.prompt}</div>}
          {event.done_summary && (
            <>
              <div className="event-divider" />
              <div className="event-expanded-block">{event.done_summary}</div>
            </>
          )}
        </div>
      )}
    </article>
  )
}

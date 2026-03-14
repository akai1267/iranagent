import { useEffect, useRef, useState } from 'react'

import EventRow from './EventRow'

export default function Observatory({ events, connected, agentStatus }) {
  const listRef = useRef(null)
  const [paused, setPaused] = useState(false)
  const statusRows = agentStatus ? Object.entries(agentStatus) : []

  useEffect(() => {
    if (paused) {
      return
    }
    if (listRef.current) {
      listRef.current.scrollTop = 0
    }
  }, [events, paused])

  return (
    <section className="observatory-shell" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}>
      <header className="observatory-header">
        <span className="observatory-title">OBSERVATORY</span>
        <span className="timestamp">
          <span className="live-dot" /> {connected ? 'LIVE' : 'OFFLINE'}
        </span>
      </header>

      <div className="observatory-list" ref={listRef}>
        {events.length === 0 ? (
          <div className="observatory-empty">
            <span className="live-dot" />
            <span>
              {connected ? 'Connected. No events yet.' : 'Observatory offline. Reconnecting...'}
            </span>
            {statusRows.length > 0 ? (
              <div className="observatory-empty-status">
                {statusRows.map(([agent, status]) => (
                  <div key={agent} className="observatory-status-row">
                    <span>{agent}</span>
                    <span className={`status-pill ${status === 'ok' ? 'ok' : 'down'}`}>{status}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : (
          events.map((event, index) => <EventRow key={event.seq || `${event.timestamp || index}-${index}`} event={event} />)
        )}
      </div>
    </section>
  )
}

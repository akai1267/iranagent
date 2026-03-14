import { useState } from 'react'

import { API_BASE } from '../../lib/api'
import ChatInput from './ChatInput'
import Message from './Message'

function timestampLabel() {
  return new Date().toLocaleString([], {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
}

async function streamWords(answer, onChunk) {
  const words = String(answer || '').split(/\s+/).filter(Boolean)
  let current = ''
  for (let i = 0; i < words.length; i += 1) {
    current += `${i === 0 ? '' : ' '}${words[i]}`
    onChunk(current)
    await new Promise((resolve) => window.setTimeout(resolve, 20))
  }
}

export default function Chat({ onCitation, paused = false }) {
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)

  async function handleSend(question, urgent) {
    if (paused) {
      return
    }

    setMessages((previous) => [
      ...previous,
      { id: crypto.randomUUID(), role: 'user', content: question },
      { id: crypto.randomUUID(), role: 'assistant', content: '● thinking...' },
    ])

    setLoading(true)
    try {
      const response = await window.fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, urgent }),
      })
      const data = await response.json()

      const assistantId = crypto.randomUUID()
      setMessages((previous) => [
        ...previous.slice(0, -1),
        { id: assistantId, role: 'assistant', content: '' },
      ])

      await streamWords(data.answer, (chunk) => {
        setMessages((previous) =>
          previous.map((message) =>
            message.id === assistantId ? { ...message, content: `${chunk} ▌` } : message,
          ),
        )
      })

      setMessages((previous) =>
        previous.map((message) =>
          message.id === assistantId
            ? { ...message, content: String(data.answer || 'No response received.') }
            : message,
        ),
      )
    } catch {
      setMessages((previous) => [
        ...previous.slice(0, -1),
        { id: crypto.randomUUID(), role: 'assistant', content: 'I hit an error trying to answer that.' },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="chat-shell">
      {messages.length === 0 ? (
        <div className="chat-empty">
          <p>Ask me anything about the conflict.</p>
          <p>I'll answer from what I've written and what I know.</p>
        </div>
      ) : (
        <>
          <div className="section-rule">{timestampLabel()}</div>
          <div className="chat-history">
            {messages.map((message) => (
              <Message key={message.id} message={message} onCitation={onCitation} />
            ))}
          </div>
        </>
      )}

      {paused ? <div className="chat-paused-note">Chat temporarily paused.</div> : null}
      <ChatInput onSend={handleSend} disabled={loading} paused={paused} />
    </section>
  )
}

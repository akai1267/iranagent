import { useState } from 'react'

export default function ChatInput({ onSend, disabled, paused = false }) {
  const [value, setValue] = useState('')
  const [urgent, setUrgent] = useState(false)

  const submit = () => {
    const trimmed = value.trim()
    if (!trimmed || disabled || paused) {
      return
    }
    onSend(trimmed, urgent)
    setValue('')
  }

  return (
    <footer className={`chat-input-row ${paused ? 'paused' : ''}`}>
      <label className="urgent-toggle">
        <input
          type="checkbox"
          checked={urgent}
          disabled={disabled || paused}
          onChange={(event) => setUrgent(event.target.checked)}
        />
        urgent
      </label>

      <textarea
        className="chat-input"
        rows={1}
        value={value}
        disabled={disabled || paused}
        placeholder={paused ? 'Chat temporarily paused.' : 'Ask anything...'}
        onChange={(event) => {
          if (paused) {
            return
          }
          setValue(event.target.value)
          event.target.style.height = 'auto'
          event.target.style.height = `${event.target.scrollHeight}px`
        }}
        onKeyDown={(event) => {
          if (paused) {
            event.preventDefault()
            return
          }
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            submit()
          }
        }}
      />

      <button type="button" className="send-btn" onClick={submit} disabled={disabled || paused}>
        SEND ↵
      </button>
    </footer>
  )
}

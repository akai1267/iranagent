import { useState } from 'react'

export default function OpenQuestions({ questions }) {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <section className="card card-accent-left open-questions">
      <header className="open-questions-header">
        <span className="overline">OPEN QUESTIONS</span>
        <button type="button" className="tiny-btn" onClick={() => setCollapsed((value) => !value)}>
          {collapsed ? 'expand ▼' : 'collapse ▲'}
        </button>
      </header>

      {!collapsed && (
        <ul className="open-questions-list">
          {questions.length === 0 ? (
            <li className="muted-row">No active questions yet.</li>
          ) : (
            questions.map((question) => (
              <li key={question.id} className="question-row">
                <span className="question-bullet">●</span>
                <span className="question-text">{question.question}</span>
                <span className="timestamp">{Number(question.priority || 0).toFixed(2)}</span>
              </li>
            ))
          )}
        </ul>
      )}
    </section>
  )
}

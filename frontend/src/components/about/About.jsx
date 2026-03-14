export default function About() {
  return (
    <section className="about-shell">
      <header className="about-hero card">
        <div className="overline">ABOUT THIS SYSTEM</div>
        <h2 className="about-title">Iran War Monitor AI Agentic Analyst</h2>
        <p className="about-lede">
          This platform is a multi-agent intelligence workflow focused on the Iran conflict. It watches live sources,
          triages what matters, builds evolving analysis, and surfaces internal reasoning in real time through the
          Observatory.
        </p>
      </header>

      <section className="about-section card">
        <div className="overline">WHAT IT IS</div>
        <p>
          It is not a generic chatbot. It is a continuously running analyst stack: ingestion, significance scoring,
          prioritization, deep research, and publishing. The left panel is the output (Feed, Theories, Chat), while
          the right panel is the process trace (Observatory).
        </p>
      </section>

      <section className="about-section card">
        <div className="overline">HOW IT FLOWS</div>
        <div className="about-flow">
          <div className="about-node">Sources</div>
          <span className="about-arrow">→</span>
          <div className="about-node">Monitor</div>
          <span className="about-arrow">→</span>
          <div className="about-node">Orchestrator</div>
          <span className="about-arrow">→</span>
          <div className="about-node">Researcher</div>
          <span className="about-arrow">→</span>
          <div className="about-node">Feed + Theories</div>
        </div>
        <p className="about-caption">
          Every major action is logged into Observatory events so you can see what the system read, decided, wrote, or
          interrupted.
        </p>
      </section>

      <section className="about-section card">
        <div className="overline">AGENTS</div>
        <div className="about-agents-grid">
          <article className="about-agent-card agent-orchestrator">
            <h3>[orchestrator]</h3>
            <p>Routes signal priority, manages interrupts, and applies system mode shifts under budget pressure.</p>
          </article>
          <article className="about-agent-card agent-monitor">
            <h3>[monitor]</h3>
            <p>Polls RSS, X via Nitter RSS, and Telegram channels, then tags items by conflict significance.</p>
          </article>
          <article className="about-agent-card agent-researcher">
            <h3>[researcher]</h3>
            <p>Builds analytical posts, updates working theories, answers user questions, and performs deep dives.</p>
          </article>
          <article className="about-agent-card agent-source-monitor">
            <h3>[source_monitor]</h3>
            <p>Audits source health and proposes source additions/removals for human approval.</p>
          </article>
        </div>
      </section>

      <section className="about-section card">
        <div className="overline">DATA + MEMORY</div>
        <ul className="about-list">
          <li>
            Analysis posts, open questions, and observatory history are persisted in SQLite on mounted storage
            (`/memory/posts.db`).
          </li>
          <li>Redis is used for pub/sub, sequencing, heartbeats, and real-time coordination between agents.</li>
          <li>
            Observatory events survive refreshes and reconnects using sequence catch-up, so UI refresh does not reset
            agent state.
          </li>
        </ul>
      </section>

      <section className="about-section card">
        <div className="overline">BUDGETING + SAFETY</div>
        <ul className="about-list">
          <li>Global shared LLM budgeting is enforced across agents to protect free-tier limits.</li>
          <li>Background work degrades first under pressure; interactive pathways are preserved.</li>
          <li>Ingestion caps and pacing are configured for low-cost continuous operation.</li>
        </ul>
      </section>

      <section className="about-section card">
        <div className="overline">WHAT TO EXPECT</div>
        <ul className="about-list">
          <li>Feed: concise, opinionated analyst posts with citations and updates to prior takes.</li>
          <li>Theories: a living strategic model that changes when the evidence changes.</li>
          <li>Observatory: transparent visibility into model activity and agent decisions.</li>
        </ul>
      </section>
    </section>
  )
}

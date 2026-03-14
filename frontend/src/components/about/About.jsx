export default function About() {
  return (
    <section className="about-shell">
      <header className="about-hero card">
        <div className="overline">ABOUT</div>
        <h2 className="about-title">Iran War Monitor AI Agentic Analyst</h2>
        <p className="about-lede">
          This app is now intentionally minimal. It focuses on one job: generating a readable current-picture analysis
          from IranMonitor data and showing it in the `CURRENT PICTURE` tab.
        </p>
      </header>

      <section className="about-section card">
        <div className="overline">HOW IT WORKS</div>
        <p>
          Every few hours, the backend fetches the IranMonitor export prompt from
          `https://www.iranmonitor.org/api/export-prompt`, appends the configured style instruction, sends it to the
          model, and stores the generated analysis. The UI polls for the latest stored snapshot and renders it.
        </p>
      </section>

      <section className="about-section card">
        <div className="overline">PIPELINE</div>
        <div className="about-flow">
          <div className="about-node">IranMonitor API</div>
          <span className="about-arrow">→</span>
          <div className="about-node">Researcher Loop</div>
          <span className="about-arrow">→</span>
          <div className="about-node">SQLite Snapshot</div>
          <span className="about-arrow">→</span>
          <div className="about-node">Current Picture Tab</div>
        </div>
      </section>

      <section className="about-section card">
        <div className="overline">STORAGE</div>
        <ul className="about-list">
          <li>Current picture snapshots are stored in SQLite (`/memory/posts.db`).</li>
          <li>On upstream or model failure, the app keeps serving the last successful snapshot.</li>
        </ul>
      </section>

      <section className="about-section card">
        <div className="overline">COST + SAFETY</div>
        <ul className="about-list">
          <li>Refresh cadence is configurable and defaults to every 3 hours.</li>
          <li>Prompt-hash checks avoid unnecessary regeneration when source content is unchanged.</li>
          <li>Strict caps are applied to keep model usage inside free-tier limits.</li>
        </ul>
      </section>
    </section>
  )
}

export default function About() {
  return (
    <section className="about-shell">
      <header className="about-hero card">
        <div className="overline">ABOUT</div>
        <h2 className="about-title">GTM Leads Research Analyst</h2>
        <p className="about-lede">
          This demo shows what a lead-research console could feel like before any live crawling or scoring exists. It is
          designed to turn public market signals into a readable GTM brief and a Clay-ready account export.
        </p>
      </header>

      <section className="about-section card">
        <div className="overline">HOW TO READ IT</div>
        <p>
          The left pane is your daily brief: what changed, who moved in the queue, and the signals behind it. The right
          pane is your account board: queue movers, active lanes to work, play patterns, priority accounts, and what to
          watch on the next check-in.
        </p>
      </section>

      <section className="about-section card">
        <div className="overline">EXPORT TO CLAY</div>
        <p>
          The export button produces a client-side CSV with one row per company. It is meant to be a clean base table
          for Clay, not a finished prospecting system. The idea is that research narrows the field first, then Clay
          handles enrichment and downstream workflow.
        </p>
      </section>

      <section className="about-section card">
        <div className="overline">PIPELINE</div>
        <div className="about-flow">
          <div className="about-node">Public signals</div>
          <span className="about-arrow">-&gt;</span>
          <div className="about-node">Synthesis</div>
          <span className="about-arrow">-&gt;</span>
          <div className="about-node">Account hypotheses</div>
          <span className="about-arrow">-&gt;</span>
          <div className="about-node">Clay-ready export</div>
        </div>
      </section>

      <section className="about-section card">
        <div className="overline">WHY MOCKED</div>
        <ul className="about-list">
          <li>The frontend is intentionally self-contained, so the demo works without any backend dependency.</li>
          <li>The companies, signals, and reasoning are illustrative, not live research output.</li>
          <li>A real version would replace the local snapshot with live ingestion, clustering, review, and export logic.</li>
        </ul>
      </section>
    </section>
  )
}

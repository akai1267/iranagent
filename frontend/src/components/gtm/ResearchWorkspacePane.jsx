import { downloadClayCsv } from '../../lib/exportClayCsv'
import AccountWatchRow from './AccountWatchRow'
import PatternCard from './PatternCard'
import QuestionCard from './QuestionCard'

function moveClass(direction) {
  const normalized = String(direction || '').toLowerCase()
  if (normalized === 'up') {
    return 'status-chip status-chip-active'
  }
  if (normalized === 'new') {
    return 'status-chip status-chip-verifying'
  }
  return 'status-chip status-chip-watch'
}

export default function ResearchWorkspacePane({ snapshot, loading, error }) {
  if (loading) {
    return (
      <section className="right-pane research-workspace-pane">
        <p className="muted-row">Loading account board...</p>
      </section>
    )
  }

  if (error) {
    return (
      <section className="right-pane research-workspace-pane">
        <p className="muted-row">{error.message}</p>
      </section>
    )
  }

  const accounts = snapshot.workspace.accounts || []
  const exportDisabled = accounts.length === 0

  return (
    <section className="right-pane research-workspace-pane">
      <header className="workspace-header card">
        <div className="workspace-header-copy">
          <div className="overline">ACCOUNT BOARD</div>
          <h2 className="pane-title">Who to work and why</h2>
          <p className="workspace-intro">{snapshot.workspace.intro}</p>
        </div>
        <div className="workspace-header-actions">
          <button
            type="button"
            className="export-btn"
            disabled={exportDisabled}
            onClick={() => downloadClayCsv(snapshot)}
          >
            Export Clay CSV
          </button>
          <p className="export-helper">
            {exportDisabled ? 'No accounts ready to export' : 'One row per company for Clay enrichment'}
          </p>
        </div>
      </header>

      {snapshot.workspace.movements?.length ? (
        <section className="workspace-section">
          <div className="section-header">
            <div className="overline">QUEUE MOVERS</div>
          </div>
          <div className="workspace-stack">
            {snapshot.workspace.movements.map((movement) => (
              <article key={movement.id} className="workspace-card movement-card">
                <div className="workspace-card-header">
                  <h3 className="workspace-card-title">{movement.account}</h3>
                  <span className={moveClass(movement.direction)}>{movement.direction}</span>
                </div>
                <p className="workspace-card-copy">{movement.detail}</p>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      <section className="workspace-section">
        <div className="section-header">
          <div className="overline">ACTIVE LANES</div>
        </div>
        <div className="workspace-stack">
          {snapshot.workspace.questions.map((question) => (
            <QuestionCard key={question.id} question={question} />
          ))}
        </div>
      </section>

      <section className="workspace-section">
        <div className="section-header">
          <div className="overline">PLAY PATTERNS</div>
        </div>
        <div className="pattern-grid">
          {snapshot.workspace.patterns.map((pattern) => (
            <PatternCard key={pattern.id} pattern={pattern} />
          ))}
        </div>
      </section>

      <section className="workspace-section">
        <div className="section-header">
          <div className="overline">PRIORITY ACCOUNTS</div>
        </div>
        <div className="workspace-card account-watch-list">
          {accounts.map((account) => (
            <AccountWatchRow key={account.id} account={account} />
          ))}
        </div>
      </section>

      <section className="workspace-lower-grid">
        <article className="workspace-card">
          <div className="overline">STILL UNCLEAR</div>
          <ul className="workspace-list">
            {snapshot.workspace.unknowns.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </article>

        <article className="workspace-card">
          <div className="overline">WATCH NEXT</div>
          <ul className="workspace-list">
            {snapshot.workspace.nextMoves.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </article>
      </section>
    </section>
  )
}

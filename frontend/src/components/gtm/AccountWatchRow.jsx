function statusClass(status) {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'promising') {
    return 'status-chip status-chip-active'
  }
  if (normalized === 'needs validation') {
    return 'status-chip status-chip-watch'
  }
  return 'status-chip status-chip-verifying'
}

export default function AccountWatchRow({ account }) {
  return (
    <article className="account-watch-row">
      <div className="account-watch-main">
        <div className="account-watch-topline">
          <h3 className="account-watch-name">{account.companyName}</h3>
          <span className={statusClass(account.status)}>{account.status}</span>
        </div>
        <div className="account-watch-subline">
          <span>{account.domain}</span>
          <span className="account-watch-divider">/</span>
          <span>{account.category}</span>
          <span className="account-watch-divider">/</span>
          <span>{account.employeeBand}</span>
        </div>
        <p className="account-watch-rationale">{account.rationale}</p>
      </div>
    </article>
  )
}

const CSV_COLUMNS = [
  'company_name',
  'domain',
  'website',
  'category',
  'employee_band',
  'hq_region',
  'status',
  'confidence',
  'why_now',
  'lead_hypothesis',
  'pain_hypothesis',
  'suggested_angle',
  'signal_count',
  'source_window',
  'notes',
]

function escapeCsvCell(value) {
  const stringValue = value == null ? '' : String(value)
  if (!/[",\n]/.test(stringValue)) {
    return stringValue
  }
  return `"${stringValue.replace(/"/g, '""')}"`
}

function formatFilenameDate(generatedAt) {
  const date = new Date(generatedAt)
  if (Number.isNaN(date.getTime())) {
    return 'unknown-date'
  }
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function toCsvRow(account, windowLabel) {
  return {
    company_name: account.companyName,
    domain: account.domain,
    website: account.website,
    category: account.category,
    employee_band: account.employeeBand,
    hq_region: account.hqRegion,
    status: account.status,
    confidence: account.confidence,
    why_now: account.whyNow,
    lead_hypothesis: account.leadHypothesis,
    pain_hypothesis: account.painHypothesis,
    suggested_angle: account.suggestedAngle,
    signal_count: account.signalCount,
    source_window: windowLabel,
    notes: account.notes,
  }
}

export function buildClayCsv(accounts, generatedAt, windowLabel) {
  const rows = Array.isArray(accounts) ? accounts : []
  const headerLine = CSV_COLUMNS.join(',')
  const bodyLines = rows.map((account) => {
    const mapped = toCsvRow(account, windowLabel)
    return CSV_COLUMNS.map((column) => escapeCsvCell(mapped[column])).join(',')
  })

  return {
    filename: `gtm-leads-clay-export-${formatFilenameDate(generatedAt)}.csv`,
    content: [headerLine, ...bodyLines].join('\n'),
  }
}

export function downloadClayCsv(snapshot) {
  const accounts = snapshot?.workspace?.accounts || []
  if (!accounts.length) {
    return false
  }

  const { filename, content } = buildClayCsv(accounts, snapshot?.generatedAt, snapshot?.windowLabel || 'Past 7 days')
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8;' })
  const url = window.URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  window.URL.revokeObjectURL(url)
  return true
}

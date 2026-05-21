# GTM Leads Research Analyst Mock Data Schema

## Data Ownership
The frontend owns the mock snapshot. No backend endpoint is required for v1. One local snapshot object should drive summary rendering, workspace rendering, and CSV export.

## Snapshot Schema
The root object is GtmIntelSnapshot.

```ts
type GtmIntelSnapshot = {
  generatedAt: string
  windowLabel: string
  icpLabel: string
  confidence: 'low' | 'medium' | 'high'
  marketTemperature: 'cool' | 'warming' | 'hot'
  sourceCount: number
  categoryTags: string[]
  executiveRead: {
    topline: string
    markdown: string
    drivers: string[]
  }
  workspace: {
    intro: string
    questions: QuestionItem[]
    patterns: PatternItem[]
    accounts: GtmExportAccount[]
    unknowns: string[]
    nextMoves: string[]
  }
}
```

## Field Definitions
- generatedAt: ISO timestamp for the snapshot
- windowLabel: human-readable rolling window label, such as Past 7 days
- icpLabel: demo ICP label
- confidence: overall confidence in the read
- marketTemperature: current commercial heat level
- sourceCount: mocked number of signals read
- categoryTags: compact market lenses rendered as chips

## Account / Export Data Shape

```ts
type GtmExportAccount = {
  id: string
  companyName: string
  domain: string
  website: string
  category: string
  employeeBand: string
  hqRegion: string
  status: 'EARLY' | 'PROMISING' | 'NEEDS VALIDATION'
  confidence: 'low' | 'medium' | 'high'
  rationale: string
  whyNow: string
  leadHypothesis: string
  painHypothesis: string
  suggestedAngle: string
  signalCount: number
  notes: string
}
```

## Example Payload
The example snapshot should include:
- one clear topline
- 3 to 5 summary paragraphs
- at least 3 questions
- at least 3 opportunity patterns
- at least 4 account rows
- at least 3 unknowns
- at least 3 next moves

## Rendering Rules
- executiveRead.markdown is rendered as markdown paragraphs
- questions render as cards with status chips
- patterns render as compact strategy cards
- accounts render as concise rows, not heavy CRM cards
- export uses workspace.accounts exactly as stored

## Content Constraints
- tone should be strategic and plausible
- company names can be fictional but should sound realistic
- no cartoonish fake data
- summary and workspace should point at each other coherently
- account rationale should be short enough to scan

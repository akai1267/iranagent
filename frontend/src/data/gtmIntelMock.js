export const gtmIntelMock = {
  generatedAt: '2026-03-15T09:18:00Z',
  windowLabel: 'Past 7 days',
  icpLabel: 'Mid-Market B2B SaaS',
  confidence: 'high',
  marketTemperature: 'warming',
  sourceCount: 47,
  categoryTags: ['Hiring', 'Partnerships', 'Pricing', 'Outbound motion'],
  executiveRead: {
    topline:
      'The most actionable GTM opening right now is among mid-market SaaS companies that look healthy on the surface but are quietly shifting from product-led efficiency toward more deliberate pipeline creation.',
    markdown: `A clear pattern over the last week is that more mid-market SaaS teams are behaving like companies that have hit the limit of passive demand capture. The public signals are not dramatic on their own, but together they point in the same direction: more leadership hiring around revenue, more experimentation with partner motion, and more language around expansion, segmentation, and sales efficiency. That usually means the internal GTM system is being reworked, not just polished.

The interesting part is that the opportunity is not sitting in obviously distressed companies. It is sitting in companies that are still growing, still shipping, and still announcing positive moves, but are starting to show signs that self-serve or founder-led motion is no longer enough. When that happens, teams begin looking for better account selection, cleaner signal routing, and more structured outbound hypotheses.

Another pattern is that commercial complexity is rising faster than the team operating it. Several companies in this mocked set are showing combinations like new VP Marketing or RevOps hiring, pricing changes, and ecosystem language around integrations or channel partners. That usually means the company is trying to coordinate multiple routes to pipeline at once. Those are the moments where research-driven targeting gets more valuable than a generic list pull.

The best near-term leads, then, are not the loudest companies in market. They are the ones showing just enough transition signal to suggest a real GTM redesign is underway. That is where the right account list, the right timing narrative, and the right outbound angle can create leverage faster than broad enrichment alone.`,
    drivers: [
      'Revenue and marketing leadership hiring is clustering around companies moving past pure PLG.',
      'Partnership and ecosystem announcements are showing up alongside segmentation and pricing changes.',
      'More teams appear to be shifting from broad demand capture toward targeted pipeline creation.'
    ]
  },
  workspace: {
    intro:
      'The model is trying to separate ordinary growth noise from signals that suggest a company is actively redesigning how it creates pipeline.',
    questions: [
      {
        id: 'q1',
        title: 'Which hiring combinations signal a real move into outbound, not just normal team growth?',
        whyItMatters:
          'A VP Marketing hire means very different things depending on whether it lands alongside RevOps, SDR, pricing, or partnerships changes.',
        status: 'ACTIVE',
        signalRefs: ['Hiring clusters', 'Org design', 'Outbound motion']
      },
      {
        id: 'q2',
        title: 'Which partnership announcements are revenue-surface expansion versus simple brand theater?',
        whyItMatters:
          'Partner language can either be a distribution shift or a low-stakes press move, and the lead quality changes completely depending on which it is.',
        status: 'VERIFYING',
        signalRefs: ['Partnership news', 'Channel hints', 'Co-sell language']
      },
      {
        id: 'q3',
        title: 'Which accounts show signs that self-serve volume is no longer converting cleanly enough?',
        whyItMatters:
          'That is often the point where signal-based account prioritization becomes budget-justifiable.',
        status: 'WATCH',
        signalRefs: ['Pricing changes', 'Lifecycle roles', 'Expansion messaging']
      }
    ],
    patterns: [
      {
        id: 'p1',
        title: 'New VP Marketing hire plus PLG stall',
        summary:
          'Several companies are adding senior demand leadership after periods where product-led growth messaging has flattened out.',
        whyNow:
          'That combination usually means the company needs more deliberate segmentation, targeting, and pipeline design.',
        archetype: 'Series B or C SaaS with decent inbound brand but inconsistent outbound structure.'
      },
      {
        id: 'p2',
        title: 'Pricing and packaging tweaks before sales motion expansion',
        summary:
          'Pricing changes are showing up ahead of broader sales and RevOps hiring, which often means the team is preparing for more structured go-to-market experiments.',
        whyNow:
          'When packaging changes arrive first, teams often need sharper account hypotheses to test the new motion.',
        archetype: 'Usage-based or hybrid SaaS products moving upmarket.'
      },
      {
        id: 'p3',
        title: 'Channel and ecosystem language around pipeline resilience',
        summary:
          'Partnership announcements are increasingly paired with efficiency language rather than pure reach language.',
        whyNow:
          'That can indicate pressure to diversify pipeline creation and improve signal quality across multiple motions.',
        archetype: 'Mid-market SaaS companies trying to stabilize growth after a noisy demand cycle.'
      }
    ],
    accounts: [
      {
        id: 'a1',
        companyName: 'Northline Labs',
        domain: 'northlinelabs.com',
        website: 'https://northlinelabs.com',
        category: 'Revenue Intelligence',
        employeeBand: '51-200',
        hqRegion: 'US East',
        status: 'PROMISING',
        confidence: 'high',
        rationale:
          'Leadership hiring and packaging changes suggest a shift from broad self-serve growth toward more structured pipeline generation.',
        whyNow: 'New GTM leadership plus repositioning language appeared in the same week.',
        leadHypothesis:
          'The team may be ready for tighter account selection and signal-driven outbound planning.',
        painHypothesis:
          'They likely have product activity data but weak translation into repeatable pipeline creation.',
        suggestedAngle: 'Lead with signal-to-sequence orchestration for mid-market outbound experiments.',
        signalCount: 5,
        notes: 'Watch for SDR or RevOps follow-on hire.'
      },
      {
        id: 'a2',
        companyName: 'RivetFlow',
        domain: 'rivetflow.io',
        website: 'https://rivetflow.io',
        category: 'Workflow Automation',
        employeeBand: '201-500',
        hqRegion: 'US West',
        status: 'PROMISING',
        confidence: 'medium',
        rationale:
          'Recent ecosystem messaging and partner language imply the team is searching for more resilient pipeline sources.',
        whyNow: 'Partnership announcements now sit next to revenue-efficiency messaging.',
        leadHypothesis:
          'They may be trying to coordinate channel, outbound, and product-led demand with better targeting discipline.',
        painHypothesis:
          'Their account prioritization may lag the complexity of the motions they are now running.',
        suggestedAngle: 'Frame around prioritizing accounts across partner and direct pipeline surfaces.',
        signalCount: 4,
        notes: 'Needs confirmation that channel motion is operational, not just narrative.'
      },
      {
        id: 'a3',
        companyName: 'SignalDock',
        domain: 'signaldock.com',
        website: 'https://signaldock.com',
        category: 'Customer Data Infrastructure',
        employeeBand: '51-200',
        hqRegion: 'UK',
        status: 'EARLY',
        confidence: 'medium',
        rationale:
          'Hiring and launch messaging suggest a company pushing upmarket but still early in commercial redesign.',
        whyNow: 'New product launch landed alongside expansion language and a growth role opening.',
        leadHypothesis:
          'The team may soon need cleaner company-level signal prioritization before scaling outbound spend.',
        painHypothesis:
          'They could be strong on product and weak on translating new positioning into focused account selection.',
        suggestedAngle: 'Offer a way to tie market signals to account hypotheses during upmarket expansion.',
        signalCount: 3,
        notes: 'Interesting, but still one cycle away from being a high-conviction target.'
      },
      {
        id: 'a4',
        companyName: 'Pondrelay',
        domain: 'pondrelay.com',
        website: 'https://pondrelay.com',
        category: 'Support Operations',
        employeeBand: '201-500',
        hqRegion: 'Nordics',
        status: 'NEEDS VALIDATION',
        confidence: 'low',
        rationale:
          'Commercial motion appears to be shifting, but the signals could still reflect routine org expansion.',
        whyNow: 'RevOps hiring and customer-segmentation language appeared close together.',
        leadHypothesis:
          'There may be a real need for better account prioritization if the company is formalizing outbound plays.',
        painHypothesis:
          'They may be struggling to align segmentation theory with practical pipeline execution.',
        suggestedAngle: 'Use a diagnostic pitch rather than a hard sell until the motion is clearer.',
        signalCount: 2,
        notes: 'Needs one more confirming signal before graduating to promising.'
      }
    ],
    unknowns: [
      'Are the hiring moves tied to a real outbound build, or are they just general leadership layering?',
      'Which partnership signals reflect pipeline diversification versus narrative positioning?',
      'Which accounts have already invested in adjacent tooling and would need a sharper displacement angle?'
    ],
    nextMoves: [
      'Check whether watched accounts add SDR, RevOps, or lifecycle roles in the next hiring cycle.',
      'Map partnership announcements against pricing or packaging changes to spot actual commercial rewiring.',
      'Track whether product launches are followed by segmentation or territory language, which usually clarifies sales intent.'
    ]
  }
}

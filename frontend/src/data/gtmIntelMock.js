export const gtmIntelMock = {
  generatedAt: '2026-03-15T09:18:00Z',
  windowLabel: 'Daily view',
  icpLabel: 'Taxwire | Indirect tax GTM',
  confidence: 'high',
  marketTemperature: 'warming',
  sourceCount: 38,
  categoryTags: ['Cross-border expansion', 'ERP change', 'Indirect tax', 'Billing complexity'],
  refreshCadenceLabel: 'Rebuilt every 3 hours',
  executiveRead: {
    topline:
      'Since the last pass, **Northline Commerce** and **LedgerLoop** moved into Taxwire\'s top tier because their expansion and systems changes are now sitting directly next to visible tax-ownership gaps, while **ParcelMint** became the clearest executive-quote-led watch after CFO **Elena Park** openly described VAT reconciliation as manual.',
    markdown: `This morning's board is sharper than yesterday's because the strongest names are no longer just showing generic growth signals. **Northline Commerce** now has a Canada and UK rollout plus a fresh Senior Tax Operations opening in the same cluster, which makes the tax-surface expansion explicit. **LedgerLoop** is in a similar position: it launched a NetSuite connector, widened EMEA billing coverage, and had VP Finance **Melissa Tran** searching for a tax manager almost at the same time. Those are not vague "finance transformation" signs. They are visible signals that indirect-tax complexity is showing up before durable ownership does.

**ParcelMint** also advanced today, but for a different reason. CFO **Elena Park** said on a webinar that VAT reconciliation was still too manual while the company pushed deeper into Germany and France. That matters because Taxwire does not need every target to publish a tax roadmap. In many cases, the better signal is an executive describing operational drag in public while the company continues expanding. That puts ParcelMint on the board as a live watch rather than just another international growth story.

The reason this should feel like a daily view and not a one-off AI memo is that the ranking is changing with each new signal. **BeaconGrid** is still on the board, but it has not moved up yet because the reseller-program story is only indirectly tied to tax pain through finance director **Joel Mercer** talking about partner-deal treatment. **CinderPay** is even less mature: multi-entity billing and a tax-systems hire suggest something may be forming, but the urgency is still implied rather than confirmed. In other words, the list is not just "good fit companies." It is a live board of who is actually moving closer to a Taxwire buying moment.

The practical takeaway is that Taxwire should bias the daily queue toward accounts where a named expansion event, a billing or ERP change, and a visible tax or finance signal are colliding in real time. Right now that means **Northline Commerce** and **LedgerLoop** are first-call names, **ParcelMint** is a strong narrative-led follow, and **BeaconGrid** plus **CinderPay** stay in monitored status until one more signal hardens the case.`,
    drivers: [
      'Northline Commerce paired its Canada and UK rollout with a new Senior Tax Operations opening.',
      'LedgerLoop stacked a NetSuite connector launch, EMEA billing expansion, and Melissa Tran\'s tax-manager search into one signal cluster.',
      'ParcelMint\'s Elena Park publicly described manual VAT reconciliation drag while the company pushed deeper into Germany and France.',
    ],
    sinceLastPass: [
      {
        label: 'Northline Commerce moved up',
        note: 'A tax-ops hiring signal joined the cross-border rollout, so this is no longer just an expansion story.',
      },
      {
        label: 'LedgerLoop hardened',
        note: 'The NetSuite and EMEA billing cluster now looks like a real tax-systems inflection, not a generic finance-upgrade narrative.',
      },
      {
        label: 'BeaconGrid held',
        note: 'Still interesting, but partner-motion complexity is visible faster than the tax urgency itself.',
      },
    ],
  },
  workspace: {
    intro:
      'This workspace is tuned for Taxwire. It is tracking which named accounts actually advanced, held, or cooled since the prior refresh so the team can work from live tax-pressure signals instead of static fit scoring.',
    movements: [
      {
        id: 'm1',
        account: 'Northline Commerce',
        direction: 'UP',
        detail:
          'Moved into the top tier after the Senior Tax Operations opening made the Canada and UK rollout look like active tax-surface expansion rather than generic growth.',
      },
      {
        id: 'm2',
        account: 'LedgerLoop',
        direction: 'UP',
        detail:
          'The Melissa Tran hiring signal now sits on top of the NetSuite and EMEA billing changes, which makes the tax-systems timing much more concrete.',
      },
      {
        id: 'm3',
        account: 'ParcelMint',
        direction: 'NEW',
        detail:
          'Elena Park\'s VAT reconciliation comment pushed ParcelMint from ambient watch into a real outbound candidate because the pain was described publicly.',
      },
      {
        id: 'm4',
        account: 'BeaconGrid',
        direction: 'HOLD',
        detail:
          'Still on the board, but it needs one more direct tax or finance-process signal before it should compete with Northline or LedgerLoop for attention.',
      },
    ],
    questions: [
      {
        id: 'q1',
        title: 'Which tracked accounts are entering new jurisdictions before they have a real indirect-tax owner in seat?',
        whyItMatters:
          'Northline Commerce, ParcelMint, and CinderPay all show expansion language, but only one has clearly staffed ahead of the problem. That is where Taxwire can step in before manual process calcifies.',
        status: 'ACTIVE',
        signalRefs: [
          'Northline Commerce: Canada/UK rollout',
          'ParcelMint: Germany and France launch',
          'CinderPay: multi-entity billing push',
        ],
      },
      {
        id: 'q2',
        title: 'Which ERP or billing changes are likely to surface tax logic problems inside finance ops over the next quarter?',
        whyItMatters:
          'LedgerLoop and CinderPay both changed core billing or systems posture. That often exposes weak nexus mapping, invoice treatment issues, and brittle filing handoffs.',
        status: 'VERIFYING',
        signalRefs: [
          'LedgerLoop: NetSuite connector',
          'CinderPay: multi-entity billing release',
          'BeaconGrid: partner invoicing cleanup',
        ],
      },
      {
        id: 'q3',
        title: 'Which executives are already speaking in a way that reveals tax pain without explicitly calling it a tax problem?',
        whyItMatters:
          'When finance leaders talk about reconciliation drag, market-entry friction, or partner invoicing exceptions, the commercial opening is usually much closer than a formal RFP.',
        status: 'WATCH',
        signalRefs: [
          'Elena Park on VAT reconciliation',
          'Joel Mercer on partner deal treatment',
          'Melissa Tran on finance systems scaling',
        ],
      },
    ],
    patterns: [
      {
        id: 'p1',
        title: 'Cross-border launch before tax team buildout',
        summary:
          'Northline Commerce and ParcelMint both widened their geographic footprint first and only then showed evidence of tax-operations hiring or manual process strain.',
        whyNow:
          'That is the exact moment when a tax platform pitch can land as risk reduction rather than another nice-to-have finance tool.',
        archetype: 'Growth-stage software or commerce platform expanding into Canada, the UK, or the EU with lean finance ops.',
      },
      {
        id: 'p2',
        title: 'ERP or billing modernization exposing hidden tax logic',
        summary:
          'LedgerLoop and CinderPay are changing the systems layer that finance depends on, which usually pulls tax edge cases into view fast.',
        whyNow:
          'When billing architecture changes, spreadsheet-based tax logic and manual overrides stop scaling quietly.',
        archetype: 'Mid-market finance teams moving from stitched workflows into NetSuite, multi-entity billing, or cleaner revenue infrastructure.',
      },
      {
        id: 'p3',
        title: 'Marketplace and partner motion creating nexus creep',
        summary:
          'BeaconGrid\'s reseller push is the best example here: partner expansion looks like a growth story publicly but often creates messy tax treatment across states and entities.',
        whyNow:
          'Tax complexity rises before the company formally names it, so early outreach has a better chance of shaping the evaluation.',
        archetype: 'Platform companies adding reseller, marketplace, or co-sell motion without mature tax-process ownership.',
      },
    ],
    accounts: [
      {
        id: 'a1',
        companyName: 'Northline Commerce',
        domain: 'northlinecommerce.com',
        website: 'https://northlinecommerce.com',
        category: 'B2B Commerce Infrastructure',
        employeeBand: '201-500',
        hqRegion: 'US East',
        status: 'PROMISING',
        confidence: 'high',
        rationale:
          'The company expanded seller coverage into Canada and the UK, then posted for a Senior Tax Operations hire instead of showing a mature tax stack already in place.',
        whyNow: 'Expansion event and tax-ownership signal arrived in the same week.',
        leadHypothesis:
          'Northline likely needs a cleaner way to manage indirect-tax complexity before cross-border volume makes the spreadsheet layer unmanageable.',
        painHypothesis:
          'Finance is probably carrying nexus, invoicing, and filing logic in manual workflows while growth continues.',
        suggestedAngle: 'Lead with cross-border readiness and removing manual tax handling from market-entry operations.',
        signalCount: 6,
        notes: 'Highest-conviction Taxwire lead in the current mock set. Daily priority unless the signal mix cools.',
      },
      {
        id: 'a2',
        companyName: 'LedgerLoop',
        domain: 'ledgerloop.io',
        website: 'https://ledgerloop.io',
        category: 'Billing and Revenue Operations',
        employeeBand: '51-200',
        hqRegion: 'US West',
        status: 'PROMISING',
        confidence: 'high',
        rationale:
          'Melissa Tran\'s tax-manager search landed right after the company launched a NetSuite connector and started talking about broader EMEA billing coverage.',
        whyNow: 'Systems change, geographic billing change, and finance hiring all clustered together.',
        leadHypothesis:
          'LedgerLoop is likely feeling the gap between a cleaner revenue stack and a still-fragile tax process underneath it.',
        painHypothesis:
          'Tax rules may be embedded in ad hoc billing ops logic instead of something durable enough for expansion.',
        suggestedAngle: 'Frame Taxwire as the missing tax layer that keeps billing modernization from creating new finance risk.',
        signalCount: 5,
        notes: 'Strong fit if Melissa Tran or her team keeps posting about systems scale or tax hiring.',
      },
      {
        id: 'a3',
        companyName: 'ParcelMint',
        domain: 'parcelmint.com',
        website: 'https://parcelmint.com',
        category: 'Logistics SaaS',
        employeeBand: '201-500',
        hqRegion: 'UK',
        status: 'PROMISING',
        confidence: 'medium',
        rationale:
          'Elena Park described manual VAT reconciliation drag while the company expanded merchant coverage in Germany and France.',
        whyNow: 'Executive language already hints at tax friction instead of hiding it behind generic finance ops language.',
        leadHypothesis:
          'ParcelMint may be approaching the point where manual VAT workflow starts slowing international revenue motion.',
        painHypothesis:
          'EU expansion is probably forcing exception handling and reconciliation work that does not scale with current finance bandwidth.',
        suggestedAngle: 'Pitch Taxwire as a way to de-risk EU expansion without waiting for a larger in-house tax function.',
        signalCount: 4,
        notes: 'Very good story-led outreach candidate if the webinar quote is reinforced by hiring or product signals in the next pass.',
      },
      {
        id: 'a4',
        companyName: 'BeaconGrid',
        domain: 'beacongrid.com',
        website: 'https://beacongrid.com',
        category: 'Security and Device Management',
        employeeBand: '501-1000',
        hqRegion: 'US Central',
        status: 'EARLY',
        confidence: 'medium',
        rationale:
          'The reseller program launch and Joel Mercer\'s comments about partner-deal tax treatment suggest nexus and invoicing complexity may be climbing.',
        whyNow: 'Partner expansion is visible, but the internal tax response is still only indirectly visible.',
        leadHypothesis:
          'If reseller growth is real, BeaconGrid will need better indirect-tax control than finance can manage manually.',
        painHypothesis:
          'State-by-state treatment across partner deals may be creating edge-case work that currently lives in email and spreadsheet review.',
        suggestedAngle: 'Approach through partner-motion complexity rather than a generic compliance pitch.',
        signalCount: 3,
        notes: 'Worth working, but it should stay below ParcelMint until the tax urgency becomes more direct.',
      },
      {
        id: 'a5',
        companyName: 'CinderPay',
        domain: 'cinderpay.com',
        website: 'https://cinderpay.com',
        category: 'Payments Infrastructure',
        employeeBand: '51-200',
        hqRegion: 'US West',
        status: 'NEEDS VALIDATION',
        confidence: 'low',
        rationale:
          'The company is pushing multi-entity billing and global customer language, but the only direct tax signal so far is an opening for a tax systems hire.',
        whyNow: 'The systems posture changed, but it is not yet clear how urgent the tax problem feels internally.',
        leadHypothesis:
          'CinderPay may soon need a more durable tax layer if multi-entity billing adoption is real and not just roadmap marketing.',
        painHypothesis:
          'Entity complexity can outgrow the finance team\'s tax workflow long before leadership publicly says so.',
        suggestedAngle: 'Keep outreach diagnostic and tied to billing complexity rather than assuming an active buying cycle.',
        signalCount: 2,
        notes: 'Needs follow-up signals before Taxwire should spend serious cycles here.',
      },
    ],
    unknowns: [
      'Which of these companies already have a tax consultant or outsourced filing setup that would blunt near-term urgency?',
      'Are Northline Commerce and LedgerLoop treating tax hiring as a stopgap before tooling, or as the long-term answer?',
      'Which partner or marketplace motions create real nexus exposure versus just modest invoicing edge cases?',
    ],
    nextMoves: [
      'Track whether Northline Commerce and LedgerLoop add follow-on roles in tax, RevOps, or finance systems over the next two weeks.',
      'Watch for implementation language around NetSuite, international billing, or VAT reporting that makes the tax problem more concrete.',
      'Collect one more named signal on BeaconGrid and CinderPay before moving them into Taxwire\'s higher-priority outbound tier.',
    ],
  },
}

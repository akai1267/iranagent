export const gtmIntelMock = {
  generatedAt: '2026-03-15T09:18:00Z',
  windowLabel: 'Daily view',
  icpLabel: 'Taxwire | Indirect tax GTM',
  confidence: 'high',
  marketTemperature: 'warming',
  sourceCount: 38,
  categoryTags: ['Cross-border expansion', 'ERP change', 'Indirect tax', 'Billing complexity'],
  refreshCadenceLabel: 'Refreshes every 3 hours',
  executiveRead: {
    topline:
      'Since the last pass, **Northline Commerce** and **LedgerLoop** moved into Taxwire\'s top tier because their expansion and systems changes are now sitting directly next to visible tax-ownership gaps, while **ParcelMint** became the clearest executive-quote-led watch after CFO **Elena Park** openly described VAT reconciliation as manual.',
    markdown: `Today's queue is sharper than yesterday because the strongest names are no longer just showing generic growth signals. **Northline Commerce** now has a Canada and UK rollout plus a fresh Senior Tax Operations opening in the same cluster, which makes the tax-surface expansion explicit. **LedgerLoop** is in a similar position: it launched a NetSuite connector, widened EMEA billing coverage, and had VP Finance **Melissa Tran** searching for a tax manager almost at the same time. Those are not vague "finance transformation" signs. They are visible signals that indirect-tax complexity is showing up before durable ownership does.

**ParcelMint** also advanced today, but for a different reason. CFO **Elena Park** said on a webinar that VAT reconciliation was still too manual while the company pushed deeper into Germany and France. That matters because Taxwire does not need every target to publish a tax roadmap. In many cases, the better signal is an executive describing operational drag in public while the company continues expanding. That puts ParcelMint on the board as a live watch rather than just another international growth story.

The ranking should feel live because it shifts every time a new signal lands—not a static fit list you have to re-read from scratch. **BeaconGrid** is still on the board, but it has not moved up yet because the reseller-program story is only indirectly tied to tax pain through finance director **Joel Mercer** talking about partner-deal treatment. **CinderPay** is even less mature: multi-entity billing and a tax-systems hire suggest something may be forming, but the urgency is still implied rather than confirmed. In other words, the list is not just "good fit companies." It is a live board of who is actually moving closer to a Taxwire buying moment.

If you only have time for a few touches today, start with **Northline Commerce** and **LedgerLoop**—expansion, systems change, and tax signals are colliding now. **ParcelMint** is your best narrative-led follow. Keep **BeaconGrid** and **CinderPay** on watch until one more signal makes the case worth real outbound spend.`,
    drivers: [
      'Northline Commerce paired its Canada and UK rollout with a new Senior Tax Operations opening.',
      'LedgerLoop stacked a NetSuite connector launch, EMEA billing expansion, and Melissa Tran\'s tax-manager search into one signal cluster.',
      'ParcelMint\'s Elena Park publicly described manual VAT reconciliation drag while the company pushed deeper into Germany and France.',
    ],
    sinceLastPass: [
      {
        label: 'Northline Commerce — up in queue',
        note: 'Tax-ops hiring joined the Canada/UK rollout. Worth a first call today.',
      },
      {
        label: 'LedgerLoop — stronger timing',
        note: 'NetSuite + EMEA billing + Melissa Tran hiring now read as a real tax-systems moment, not generic finance uplift.',
      },
      {
        label: 'BeaconGrid — hold',
        note: 'Partner motion is visible; tax urgency still indirect. Don’t burn cycles until one more signal.',
      },
    ],
  },
  workspace: {
    intro:
      'Your Taxwire board for today: who moved up, who cooled, and which accounts are worth outbound cycles right now—ranked on live tax-pressure signals, not static ICP fit.',
    movements: [
      {
        id: 'm1',
        account: 'Northline Commerce',
        direction: 'UP',
        detail:
          'Promoted to top tier: Senior Tax Operations hire + Canada/UK rollout = tax surface expanding, not just revenue.',
      },
      {
        id: 'm2',
        account: 'LedgerLoop',
        direction: 'UP',
        detail:
          'Melissa Tran tax-manager search stacked on NetSuite + EMEA billing—timing for a tax-systems conversation just got concrete.',
      },
      {
        id: 'm3',
        account: 'ParcelMint',
        direction: 'NEW',
        detail:
          'Elena Park called out manual VAT reconciliation on a webinar—enough public pain to move from watch to outbound-ready.',
      },
      {
        id: 'm4',
        account: 'BeaconGrid',
        direction: 'HOLD',
        detail:
          'Still on the board. Needs one more direct tax or finance-process signal before it competes with Northline or LedgerLoop for your time.',
      },
    ],
    questions: [
      {
        id: 'q1',
        title: 'Expansion before tax ownership is in place',
        whyItMatters:
          'Northline, ParcelMint, and CinderPay are all pushing into new markets—but only one shows signs of staffing ahead of the problem. That gap is where Taxwire wins before spreadsheets become the system of record.',
        status: 'ACTIVE',
        signalRefs: [
          'Northline Commerce: Canada/UK rollout',
          'ParcelMint: Germany and France launch',
          'CinderPay: multi-entity billing push',
        ],
      },
      {
        id: 'q2',
        title: 'Billing or ERP changes surfacing tax pain',
        whyItMatters:
          'LedgerLoop and CinderPay both moved core systems. That usually exposes nexus gaps, invoice edge cases, and filing handoffs finance is still patching manually.',
        status: 'VERIFYING',
        signalRefs: [
          'LedgerLoop: NetSuite connector',
          'CinderPay: multi-entity billing release',
          'BeaconGrid: partner invoicing cleanup',
        ],
      },
      {
        id: 'q3',
        title: 'Exec quotes that reveal tax drag without saying “tax”',
        whyItMatters:
          'When CFOs talk about reconciliation drag, market-entry friction, or partner invoicing exceptions, the deal is often closer than a formal RFP—especially if you reach them while they are still describing the pain publicly.',
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
      'Do any of these accounts already have a tax consultant or outsourced filing that kills near-term urgency?',
      'Are Northline and LedgerLoop hiring tax ops as a bridge to tooling—or as the permanent fix?',
      'Which partner motions are real nexus events vs. minor invoicing noise?',
    ],
    nextMoves: [
      'See if Northline or LedgerLoop post follow-on tax, RevOps, or finance-systems roles in the next two weeks.',
      'Watch for NetSuite, international billing, or VAT implementation language that makes the pain concrete enough to outbound on.',
      'Get one more named signal on BeaconGrid and CinderPay before promoting them into your top outbound tier.',
    ],
  },
}

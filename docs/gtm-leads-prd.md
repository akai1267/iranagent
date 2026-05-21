# GTM Leads Research Analyst PRD

## Product Summary
GTM Leads Research Analyst is a frontend demo for an AI-assisted research console that helps go-to-market teams identify where commercial opportunity is forming. It reads like a strategic market brief on the left and a deeper internal research workspace on the right, with a Clay-ready export for account-level follow-up.

## User Persona
The primary user is a GTM operator working mid-market B2B SaaS accounts. This can be a founder, head of growth, GTM engineer, or outbound lead who wants a faster way to spot promising companies before building sequences and enrichment flows.

## Problem
Most lead generation tools are good at enrichment after you already have a list. They are weaker at answering the earlier question: which accounts are worth caring about right now, and why. Teams end up stitching together scattered hiring signals, product launches, funding notes, partnership announcements, and market shifts by hand.

## Product Promise
The product turns noisy public market signals into a compact strategic read and a more detailed research workspace. It should help a GTM team move from vague market awareness to a shortlist of account hypotheses that are clean enough to export into Clay.

## Core Experience
The main screen is split into two panes. The left side gives a past-7-days executive read: one clear thesis, a short narrative, and a small set of drivers. The right side shows the deeper research layer: the questions the model is working through, the opportunity patterns it sees, the accounts it keeps circling, the unknowns, and the next research moves.

## Clay Export Use Case
The research workspace includes a client-side CSV export. The export is not a finished SDR list. It is a clean base table for Clay with one row per company, enough structured context to guide enrichment and outbound angle development, and no backend dependency.

## Scope
In scope for v1:
- mock-backed frontend demo
- warm editorial UI
- split-pane intelligence layout
- local snapshot data contract
- Clay-friendly CSV download
- About page explaining the model

## Demo Success Criteria
The demo succeeds if a user can open the app, understand the market read in under a minute, inspect the deeper reasoning on the right, and download a plausible Clay-ready account CSV without needing any backend service.

## Out of Scope
Out of scope for v1:
- live web crawling
- contact-level lead enrichment
- CRM sync
- real lead scoring logic
- chat or agent observability
- background processing

## Future Expansion
A real version would ingest live signals from the open web, cluster them into account and category narratives, keep a rolling memory of why accounts are being watched, and expose review workflows before export. It could later support multiple ICPs, saved lists, analyst notes, and direct Clay or CRM pushes.

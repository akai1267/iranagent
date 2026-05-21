# GTM Leads Research Analyst UX Spec

## Screen Overview
The app has two tabs: INTEL and ABOUT. INTEL is the primary demo surface. ABOUT explains the product model and its mocked nature.

## Global Shell
The shell reuses the current warm editorial system: serif wordmark, mono metadata, muted paper backgrounds, and a red top accent. The app remains centered with restrained width and generous spacing.

## Header
The header shows:
- wordmark: GTM Leads Research Analyst
- right-side metadata: Demo and Past 7 days

The header should feel like a serious editorial product, not a dashboard masthead.

## Tab Navigation
Two tabs only:
- INTEL
- ABOUT

INTEL is the default tab.

## Left Pane Spec
Width target on desktop: about 38 percent.

Sections in order:
1. Overline: PAST 7 DAYS
2. Title: Executive Read
3. Updated timestamp and ICP pill
4. Topline card with one sharp thesis
5. Main summary block with 3 to 5 dense paragraphs
6. Signal meta chips: source count, confidence, temperature, categories
7. What is Driving This card with 3 short signal bullets

The left pane should answer what is happening in the market and set up the research workspace without duplicating it.

## Right Pane Spec
Width target on desktop: about 62 percent.

Sections in order:
1. Workspace header with overline, title, intro, and Export Clay CSV button
2. Core Questions section with stacked cards
3. Emerging Opportunity Patterns section with 3 to 4 pattern cards
4. Accounts the Model Keeps Circling section with compact account rows
5. Open Unknowns section
6. Next Research Moves section

The right side is the deeper operator workspace. It should feel investigatory and strategic, not like an event log.

## Clay Export Interaction
The export button sits in the right-pane header area. It is enabled when at least one account exists in the mock snapshot. Clicking it downloads a CSV immediately on the client. If there are no accounts, the button is disabled and a small helper line explains why.

## About Page Spec
The ABOUT page should contain:
- what the demo is
- what the left pane is for
- what the right pane is for
- how Clay export fits in
- why the data is mocked
- what a real version would add

Include a simple pipeline row describing the flow from public signals to synthesis to account hypotheses to export.

## Responsive Behavior
Desktop:
- left and right panes render side by side
- right pane is visibly larger

Tablet/mobile:
- panes stack vertically
- executive read appears first
- export button wraps cleanly and remains usable
- chips wrap without horizontal overflow

## Visual Rules
Keep:
- warm paper palette
- serif headings
- mono metadata
- restrained borders
- editorial spacing

Avoid:
- generic SaaS dashboard chrome
- purple gradients
- heavy metrics framing
- dark mode styling for this demo

## Empty / Loading / Error States
Loading:
- show a short loading message while the mock hook resolves

Error:
- show a muted explanation that the demo snapshot could not be loaded

Empty accounts:
- keep the workspace visible
- disable export
- show helper copy

## Acceptance Criteria
The UI is complete when the user can:
- read a concise executive summary on the left
- inspect deeper research on the right
- see watched accounts without a separate lead feed
- download a Clay-friendly CSV
- understand the mocked nature of the demo from the ABOUT page

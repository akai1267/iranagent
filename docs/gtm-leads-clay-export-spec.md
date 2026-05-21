# GTM Leads Research Analyst Clay Export Spec

## Export Goal
Produce a Clay-ready CSV with one row per company/account. The file should be clean enough to upload directly into Clay as a base table for further enrichment.

## Row Identity
Each row represents one target company/account from the mocked research workspace.

## Column Order
Use this exact order:
1. company_name
2. domain
3. website
4. category
5. employee_band
6. hq_region
7. status
8. confidence
9. why_now
10. lead_hypothesis
11. pain_hypothesis
12. suggested_angle
13. signal_count
14. source_window
15. notes

## Field Mapping
- company_name -> companyName
- domain -> domain
- website -> website
- category -> category
- employee_band -> employeeBand
- hq_region -> hqRegion
- status -> status
- confidence -> confidence
- why_now -> whyNow
- lead_hypothesis -> leadHypothesis
- pain_hypothesis -> painHypothesis
- suggested_angle -> suggestedAngle
- signal_count -> signalCount
- source_window -> snapshot.windowLabel
- notes -> notes

## CSV Escaping Rules
- wrap fields containing commas, quotes, or newlines in double quotes
- double internal quotes
- preserve stable column ordering
- do not include nested objects or arrays in a cell

## Filename Convention
Use:
`gtm-leads-clay-export-YYYY-MM-DD.csv`

The date is derived from snapshot.generatedAt.

## Empty State Behavior
If there are no accounts:
- disable export action
- show helper copy: No exportable accounts in this snapshot
- do not generate a blank file automatically

## Clay Usage Notes
This export is intentionally account-level. It is designed to seed Clay with plausible company targets and commercial context. Clay can then enrich people, firmographics, technologies, and downstream workflow steps.

## Example CSV
```csv
company_name,domain,website,category,employee_band,hq_region,status,confidence,why_now,lead_hypothesis,pain_hypothesis,suggested_angle,signal_count,source_window,notes
Northline Labs,northlinelabs.com,https://northlinelabs.com,Revenue Intelligence,51-200,US East,PROMISING,high,"New growth hires after a plateau in self-serve conversion","Likely moving from product-led motion into a more structured outbound layer","May be feeling handoff friction between product signals and pipeline creation","Lead with pipeline design and signal-to-sequence orchestration",5,Past 7 days,"Watching for SDR manager hire or outbound tooling change"
```

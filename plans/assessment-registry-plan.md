# Assessment registry: who is assessing what, where, and when

Status: 2026-11-11, a plan. A new pack, `assessments`, on the **response instance** with the
5W (`responses`, `fivew`; plans/fivew-organisations-plan.md). Modelled on OCHA's registry
for the Venezuela earthquakes (github.com/UN-OCHA/assessment-registry-venezuela-earthquakes-2026)
and the UNDAC Handbook (8th ed., 2024, F.2.2-F.2.3, in ../undac-simex).

## Why

The handbook asks the UNDAC team's Assessment and Analysis (A&A) Cell to "establish
assessment registries… and manage information about planned and ongoing assessments to
harmonise efforts and avoid assessment fatigue" (p. 146), and to share "coverage dashboards
and maps… back to the humanitarian community regularly" (F.2.2.3, p. 148; also p. 143,
fig. F.8: "an e-mail and assessment registry"). The registry is how assessments move from
uncoordinated to harmonised: comparable, synchronised in place and time, without gaps or
duplication (p. 142, after the IASC's three levels: uncoordinated, harmonised, joint).

It's the 5W's shape again: an organisation, sectors, places with P-codes, dates, a status,
a follow-up, a dashboard.

## What the Venezuela registry does, and what it lacks

What it is (read 2026-11-11; no licence in the repo, so we model its fields, not its code):

- a Kobo form on OCHA's server; a GitHub Action reads the Kobo API every 30 minutes and
  commits the submissions as JSON to a static dashboard (GitHub Pages);
- per assessment: title; sectors (select multiple: inter-cluster, shelter/NFI, early
  recovery, food security, health, nutrition, protection, WASH, education, CCCM, other);
  status (planned, ongoing, completed); frequency (single, daily, weekly, monthly, other);
  the reporting organisation, lead agency, participating organisations (all free text);
  start and end dates (the end estimated); geographic level (admin1, admin2, admin3, camp,
  whole affected area) and the admin1/2/3 P-codes covered, with locality details; the
  report and the dataset (files); methodology; notes;
- the dashboard: totals (by status, organisations, sectors, states), charts by sector, by
  state, top organisations, a searchable table with CSV export. No map.

What it lacks, and this setup gives:

| Gap | Here |
|---|---|
| Organisations typed freely ("Convite AC", "CONVITE AC") | picked from the response's organisations list, as the 5W; an Account each (E12) |
| No review: everything is public within 30 minutes | the A&A Cell reviews (a status), data checks flag what looks wrong |
| No map, though the P-codes are there | coverage by P-code: a map and gaps by sector (kobo-dash) |
| Planned assessments aren't synchronised | overlaps flagged: the same sector, the same area, overlapping dates |
| No follow-up | an agent: completed with no report, planned past its start date |
| Report links are Kobo attachment URLs in public JSON | files stay in EspoCRM; the dashboard says "report available", and its sharing level |
| Updating = submitting again | the organisation's portal (E12), or the form again, matched on the assessment's code |

## Design

### 1. An assessment

`CAssessment` (code `ASM-`), in the `assessments` pack, requires `responses`:

- **what**: title; sectors (the response's sectors list, as the 5W; select multiple); type
  of coordination (uncoordinated, harmonised, joint: the handbook's three levels, p. 142);
  methodology (key informant interviews, household survey, focus groups, direct
  observation, secondary data review, other: our list, the handbook names none); frequency;
- **who**: the response; the reporting organisation and lead organisation (the
  organisations list, or typed in: as the 5W's activities); participating organisations
  (several, from the list, or typed in); its Account (the organisation's, E12);
- **when**: start, end (estimated until it's done);
- **where**: the geographic level, the admin areas covered (several, by P-code), sites or
  camps (the sites pack's, if it's there), locality details;
- **status**: planned, ongoing, completed, report shared, cancelled;
- **review** (the A&A Cell's): new, checked, needs information, duplicate;
- **outputs**: the report and the dataset (files); for each its sharing (public, within the
  response, on request); a link if it's published elsewhere (ReliefWeb, HDX);
- **data checks**: ends before it starts (refused, as the 5W); completed with no report
  after 14 days; an area outside the response's country; another organisation's assessment
  of the same sector and area with overlapping dates (the AAWG's synchronising: a flag, not
  a refusal).

**Who sees it.** The registry is meant to be shared across the response (the Venezuela one
is public). So an assessment is in its response's team and every cluster project's team
in the response, not only its sectors': any cluster's people can see who is assessing
where. Editing as the 5W: its organisation (portal), the cluster leads of its sectors,
OCHA. See "Questions".

### 2. Coverage: one row per area

A dashboard's map counts rows by P-code, one per area. So each assessment's areas are
also `CAssessmentArea` records (assessment, area, P-codes up its parents, sector list,
status, dates copied), kept by the assessment's formula: an area added makes its row, an
area removed marks its row not current. That gives the coverage map and the gaps (a sector
with no assessment in an area). The pcodes and inherit traits do most of it.

### 3. Shared with the 5W, moved to `responses`

What phase 1 of E12 put in `fivew` that assessments need too moves to the `responses` pack:

- Account ↔ COrganisation, `cAcronym`, `cOrgType`;
- finding or making an organisation's Account: a trait, `account_from_organisation`
  (the registration's block, generalised: the list entry, else the typed name);
- the teams of a response's records by cluster: a trait, `teams_from_clusters` (the
  response's teams and those of its projects in the record's sectors; CResponder's formula
  today), with an "all clusters" option for assessments.

So the `assessments` pack stands without `fivew`, and the 5W's formulas get shorter.

### 4. The form and the connection

A Kobo form, `assessment-registration` (generated, as kobo/forms/melissa.py makes the 5W's),
with the Venezuela form's questions, and the response's lists (responses.csv,
organisations.csv, areas.csv) instead of free text. Its template makes the CAssessment;
the areas come from a repeat (one row per area, so one CAssessmentArea each) or, if the
bridge's select-multiple lookup works for links, a select multiple of P-codes. Sending it
again with the assessment's code (prefilled in the email's link, as the CSO update form)
updates it.

### 5. Follow-up

An agent, "Assessments: follow-up", daily, rules only (as "5W: no report"):

- completed 14 days ago, no report: a task for the A&A Cell, and the organisation's people
  emailed (their Contacts, E12);
- planned, its start date passed: ask whether it started (a task);
- an overlap flagged: a task for the A&A Cell to put both organisations in touch.

### 6. The dashboard

kobo-dash, from feeds scoped to the response's team (as the CSO dashboards):

- totals by status, sector, organisation;
- the coverage map (assessment areas by admin1 and admin2), by sector;
- gaps: areas with no assessment for a sector; overlaps;
- a timeline of planned and ongoing assessments;
- the table: title, organisation, sectors, status, dates, report available and its
  sharing (never the file itself on a public page).

A public version, as Venezuela's, is a kobo-dash public dashboard on the checked
assessments only, showing nothing marked "within the response" or "on request".

## Phases

0. **Shared pieces to `responses`**: Account ↔ COrganisation and its fields, the
   `account_from_organisation` and `teams_from_clusters` traits; CResponder's formula on
   them. Tests: fivew unchanged.
1. **The registry**: CAssessment, roles, layouts, the form and its template, the
   connection; tests (an assessment in the whole response's teams, its organisation's
   Account, the review status, refused dates).
2. **Coverage and checks**: CAssessmentArea, the data checks (overlaps). Tests.
3. **Follow-up**: the agent. Tests (agents suite).
4. **Dashboard**: the coverage map, gaps, timeline; a public view.
5. **Portal and manual**: assessments in the organisation portal (E12), an "Assessments"
   page.

## Questions

- **Who sees an assessment**: the whole response (suggested: the registry is a shared
  good), or only its sectors' clusters, as the 5W?
- **Review before it shows**: on the response's dashboard straight away, with
  "not checked yet" (suggested), or only once checked? The public view: checked only.
- **The form's language and lists**: the Venezuela form is Spanish, its sectors list
  differs a little from the 5W's (inter-cluster, shelter/NFI, early recovery); use the
  response's sectors list (suggested), with "inter-cluster" added.
- **Joint assessments** (the MIRA-like multi-sector one the AAWG runs with the government,
  pp. 164-165): one record of type "joint", with many participating organisations, or a
  project of its own? Suggested: a record, at first.

## Other response workflows the handbook describes

Candidates for packs on the same instance, most useful and buildable first (the
handbook's pages; field lists are its where it gives them, otherwise to be agreed):

1. **Contact list and "who's here" registration** (p. 77: a registration link and QR code
   for the response's contacts; p. 183: names, organisation, function, email, phone by
   GSM, Signal or WhatsApp, satellite, location; not posted on the VOSOCC). Mostly E12
   (organisations' Contacts) plus a registration form: small.
2. **Meeting schedule** (p. 183: "an up-to-date schedule… online and physically in the
   OSOCC"; p. 146: action points). EspoCRM's own Meeting, linked to the response or a
   cluster; a public calendar view. Small.
3. **Team arrivals: EMTs and other international teams** (Reception and Departure Centre,
   pp. 104-105; EMT offer, acceptance, registration and licence, tasking to a site,
   monitoring, exit, pp. 262-264). Not USAR: INSARAG's ICMS does that (pp. 246-247). A
   team is an Account with a status; tasking links it to a site (the sites pack). Medium.
4. **Access constraints log** (AMRF, p. 229: damaged infrastructure, weather, terrain,
   bureaucratic restrictions, diversion, insecurity, attacks on aid workers). A dated
   record at an admin area, open or resolved; sensitive in conflicts. Medium.
5. **Civil-military requests for assistance** (pp. 55, 268-270: an RFA mechanism,
   deconfliction notifications). The support pack's cases, routed to the CMCoord cell.
   Medium; its fields from OCHA's RFA templates, not the handbook.
6. **Community feedback** (AAP, pp. 219-220: map the mechanisms, act on feedback, trends
   in sitreps). Cases with categories and areas; `plans/community-feedback-plan.md` has a
   draft.
7. **Offers of assistance** (private sector asks, pp. 236-237; member states' offers,
   p. 310): offers matched to needs. Medium; the CSO matching (PRODUCT-424) is the same
   pattern.
8. Lower: a products log (sitreps, maps, briefs: title, date, link, audience); financing
   (Flash Appeal, CERF, pp. 237-239), where FTS is the system of record.

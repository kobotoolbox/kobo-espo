# Workflow E: a response's 5W (who does what, where, when, for whom)

Status: 2026-11-08. Phases 1–3 built (organisations, admin areas, activities, one per
submission), with a draft of phase 0's activity types; next phases 4 (repeat groups) and 6
(the dashboard, in kobo-dash). It builds on cluster projects (`CProject`, the cluster roles,
`tests/cases/projects.py`; manual page "Cluster projects").

Built (2026-11-08), and what changed from the design below:
- **Organisations are `CResponder` ("Responding organisation"), not Account fields.** One
  per organisation *and response*: an organisation in two responses registers twice, and
  its Account (EspoCRM's own, found or made by name through `[requester]`) is shared. Its
  focal point is a Contact. It's in the response's team and in the teams of the response's
  projects in the clusters it works in (formula; a new project in one of its clusters adds
  its team too). Registering again (the same response and acronym, `registrationKey`)
  updates it. Form `kobo/forms/responder-registration.json`, template
  `responder-registration.toml`.
- **Clusters are codes** (`etc`, `wash`... with labels), since Kobo choice names have no
  spaces; projects made before were migrated by the seed.
- **Short codes** on responses, projects, organisations, activities, tasks and applications
  (`RSP-7K3Q`, as Ponto's; `espo/formula/_code.formula`): read-only, unique, searchable,
  and what Kobo lists use as choice names (a list's `name = "code"`, a link's
  `lookup = "code"`), instead of EspoCRM's 17-character ids. Sites keep their site code,
  admin areas their P-code.
- **Admin areas**: `CAdminArea` (P-code, level, parent, country), seeded from
  `espo/seed/data/admin-areas-<iso3>.json`; Jamaica's 14 parishes (JM01 Kingston ...
  JM14 Saint Catherine) for the tests. Check them against the COD-AB (the humanitarian
  geocoder's admin1 CSV, `~/Desktop/work/repos/jamaica-geocoder`) before real use; that
  service's per-level CSVs (`name,label` by P-code) are the import for other countries.
- **Activities** (`CActivity`): organisation, project, response, admin area, site, type
  (a draft list, `ACTIVITY_TYPES` in the seed, prefixed by cluster), status, dates, the six
  sex and age groups, people reached (summed by the formula), households, quantity and
  unit. In the project's teams; named "ACRONYM · type · date"; the organisation's last
  report moves on. Refused (API Before Save): ending before it starts, an organisation of
  another response, or not registered for the project's cluster. Form
  `activity-report.json`, per response like the site visit (`team = "Response: …"` lists:
  `responders.csv`, `projects.csv`, `areas.csv`).
- Roles: Cluster Lead edits the project's activities and organisations; Cluster Partner
  reports and edits their own; Cluster Viewer reads; everyone reads admin areas.
- Tests: `tests/cases/fivew.py` 33/33 (codes, teams from clusters, activities, guards,
  who sees what, admin areas); `connection.py` W7–W10 (the two forms through the bridge).

## Goal

During a response such as *Hurricane Melissa Response*, the information manager runs the
5W in EspoCRM:

1. **Organisations register** through a Kobo form as responding organisations: name,
   acronym, type, contacts, the clusters and areas they work in.
2. **They report their activities**, daily or weekly, through Kobo (or a spreadsheet):
   what, where (admin area and site), when, status, and people reached.
3. **The IM team follows up** in EspoCRM: who registered but hasn't reported, reports that
   look wrong, gaps and overlaps, with notes and tasks.
4. **The 5W's outputs** (people reached by area and cluster, who works where, the map) come
   from a dashboard that reads EspoCRM, not from EspoCRM's own screens.

EspoCRM is the system of record and the follow-up tool; it is not the analysis tool (see
"What stays out").

## What already exists

- Kobo → EspoCRM records, created or updated by a match (`[record] match`), with media,
  links found by a code (`lookup`), and datetimes in UTC (kobo-espo-bridge).
- Lists from EspoCRM onto Kobo forms (`[[list]]`, CSV media), by team: the forms pick
  organisations, projects, sites and areas from what EspoCRM holds.
- Cluster projects with their own teams, and the cluster roles; tasks on sites and cases.
- Agents on a schedule (`trigger = schedule`, `idleField`/`idleDays`): the "not reported"
  check is one of these.
- EspoCRM's own **Account** (organisations), **Contact** (their people) and CSV import.
- Not there: repeat groups (the bridge leaves them out with a warning), admin areas, an
  Activity record, any chart or summed report (core EspoCRM has none; the Advanced Pack is
  paid and we don't use it).

## Design

### 1. Organisations are Accounts

The registration form makes or updates an **Account** (EspoCRM's own), matched on an
organisation code given at registration (or the acronym), in the response's team:

- `cOrgType` (UN agency, INGO, NNGO, Red Cross / Red Crescent, Government, Private sector,
  Other), `cAcronym`, `cOrgCode`;
- the clusters they work in (multi-enum), linked to the response's **projects**
  (Account ↔ CProject, many-to-many): a cluster's team sees the organisations in it;
- their focal points as **Contacts**, linked to the Account.

An organisation's own users, if they get accounts at all, are Cluster Partners in a team of
their organisation (one team per organisation), so they see only their own reports. That's
optional: most organisations report through Kobo and never sign in.

### 2. Admin areas: a reference list with P-codes

`CAdminArea`: P-code, name, level (admin1..3), parent P-code, from the country's COD
(common operational dataset), imported once per response by CSV. No team: everyone reads
them, like Standards. The report forms pick areas from `areas.csv` (with a `choice_filter`
on the parent for admin2 under admin1); an activity links to its area by P-code
(`lookup = "pcode"`).

### 3. Activities: one record per activity

`CActivity`: organisation (Account), project (CProject, so its teams), activity type (per
cluster, an enum kept with the project's cluster), admin area, site (optional), start and
end dates, status (planned / ongoing / completed), people reached by sex and age group
(int fields: girls, boys, women, men, elderly women, elderly men; a `total` the formula
sums), the report it came from, and the reporting date.

It takes its project's teams (formula, as sites do): the cluster's team and the response's
coordinators see it, and nobody else.

### 4. Reports with several activities: repeat groups in the bridge

A daily report is "organisation X, today: these activities", one Kobo repeat group. The
bridge needs a way to make **one record per repeat row**:

```toml
[[repeat]]
group = "activities"           # the repeat group's name
entity = "CActivity"
match = { koboRowKey = "{_uuid}/{_index}" }   # idempotent per row
link = "report"                # each row links to the record [record] made (CActivityReport)
fields = [ ... ]               # as [[field]], the row's questions; the parent's by ../name
```

- A row's key is the submission's uuid plus the row's index, so re-running a submission
  (edits in Kobo) updates the same rows and doesn't duplicate them. Rows removed in an edit
  are marked, not deleted.
- `propose` offers the repeat group's questions as a second entity instead of leaving them
  out.
- This is the largest piece of work here, and it's in kobo-espo-bridge (shared with
  kobo-in-a-box), with its own unit tests against fake_kobo first. rodekruis/kobo-connect
  does the same (we didn't take it in November; now there's a reason).

The simpler fallback, if (4) waits: a form with one activity per submission, and "add
another" as a new submission. That works with the bridge as it is.

### 5. Other ways in

- **Spreadsheets**: EspoCRM's import (CSV) into Activities, with a template sheet whose
  columns are the field names. Mapping the organisation and area by name or P-code is part
  of EspoCRM's import.
- Later, if needed: an MCP tool that checks a sheet against the areas and organisations
  and reports what doesn't match, before importing.

### 6. Follow-up

- An agent on a schedule (rules only, no model): every morning, each organisation in an
  active project with no activity reported in N days gets a task for the project's IM
  focal point ("No report from X since …"), at most one open per organisation.
- Data checks as formula guards where they're certain (end before start, total of zero for
  a completed activity) and as an agent's flags where they're judgement (a sudden jump).
- Notes and tasks on organisations and activities, as everywhere else.

### 7. Outputs: a dashboard, not EspoCRM

The 5W's tables and map are a kobo-dash dashboard: EspoCRM becomes a source there (an
EspoCRM feed, polled with a read-only API user limited to a response's or project's team
and the feed's fields), designed through kobo-mcp's dashboard tools, with the feed set up
by the EspoCRM MCP. The plan is kobo-dash's `plans/espo-source-plan.md` (2026-11-08).
EspoCRM's own list views, filters and the Kanban stay for follow-up, not for analysis.

## What stays out

- Charts and summed reports inside EspoCRM (Advanced Pack): the dashboard does it.
- Deduplicating organisations across responses: one response at a time first.
- Beneficiary-level data: 5W counts people reached, it never holds people's records.

## Phases

0. Agree the activity fields and types with a real cluster's 5W template (ETC, WASH).
1. Organisations: Account fields, the Account ↔ project link and its formula (an Account's
   teams = its projects'), the registration form and connection; tests (isolation between
   clusters for Accounts).
2. Admin areas: `CAdminArea`, a CSV import of a COD (a test country), `areas.csv` on forms.
3. Activities, one per submission: `CActivity`, its formula and roles; the report form; the
   CSV import template. Tests as projects.py.
4. Repeat groups in kobo-espo-bridge (`[[repeat]]`, `propose`, unit tests, then a real Kobo
   run); the daily report form with a repeat.
5. The "not reported" agent and the data checks.
6. The dashboard: kobo-dash's EspoCRM source (its `plans/espo-source-plan.md`), then the 5W
   dashboard on it.
7. MCP: `create_project` also sets up the project's report connection from a template.

## Risks and open questions

- **Volume**: 50 organisations × 5 activities × daily = ~7,500 rows a month per response.
  Fine for EspoCRM's database; its lists need filters (by project, area, date) to stay
  usable. Check with a generated month before phase 4 ships.
- **Repeat edits in Kobo**: how an edited submission's rows are matched again if rows were
  reordered; index-based keys break on reordering. Kobo's repeat rows have no stable id;
  consider a hidden `calculate` with `uuid()` per row in the form.
- **Per-organisation access**: one team per organisation multiplies teams; fine for tens,
  awkward for hundreds.
- **P-codes**: the COD for the country must be loaded before the forms go out.

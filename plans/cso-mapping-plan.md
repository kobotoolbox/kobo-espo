# Workflow F: CSO mapping (Kobo and WHO)

Status: 2026-11-09, not started. From the **Draft CSO mapping tool v1** (Kobo and WHO,
`ref/Draft CSO mapping tool v1.docx`): a core profile of each civil society organisation
(17 questions) and a short operational update form (6 questions), shown through four
dashboard outputs. It is built on what the 5W (Workflow E, `workflow-e-5w-plan.md`) built.

## Goal

WHO and its partners keep a map of civil society organisations (CSOs) working on health
emergencies, at two levels:

1. **Core mapping**, done once and kept up to date: who the organisation is, where it
   works, whom it reaches, what it does and could do, what it offers and seeks.
2. **Operational updates**, during an emergency or while preparing for one: in this place,
   this activity, this status, these people, this gap.

The dashboard gives the four outputs the draft asks for:

- a **searchable CSO directory**;
- a **map of operational presence and population reach**;
- a **gap-and-overlap map** of activities and locations;
- an **offer–need matching view** that connects CSOs with one another.

## What already exists

- Kobo → EspoCRM through the bridge: records matched by a code, links found by a code
  (`lookup`), **repeat groups** (`[[repeat]]`, one record per row), geopoints, media.
- Lists from EspoCRM onto Kobo forms (`[[list]]`, CSV media), filtered by team.
- From the 5W: `COrganisation` (a list everyone reads, with codes), `CFocalPoint` (people's
  contacts, which viewers can't read), `CAdminArea` (P-codes, level admin1..3, parent
  P-code; only Jamaica's are loaded), short codes (`_code.formula`), the "5W: no report"
  agent, data checks as flags.
- kobo-dash reads EspoCRM through feeds (a read-only user per feed, limited to a team and
  the feed's fields), with geo and select_multiple table kinds.
- Email through Resend (access info, notifications, and anything the seed or an agent sends).

Not there: countries and admin areas outside Jamaica, a CSO's profile fields, an update
record of this shape, any matching, and the four dashboard views.

## Design

### 1. A CSO is a `COrganisation`, with a profile

The core form makes or updates the organisation, matched on its code (`ORG-`, given at the
first submission, see 5), so a CSO keeps one record however many times it updates its
profile. Its profile fields, one per question:

| Q | Field | Type |
|---|---|---|
| 1 | `name`, `acronym` | varchar |
| 2 | `csoType` | enum (14 types). Kept apart from the 5W's `orgType`, whose codes come from the Melissa form |
| 3 | `country` (where registered) | link to the country's `CAdminArea` |
| 4 | `levels` (community … global) | multi-enum |
| 5 | focal points | `CFocalPoint`s, as in the 5W: name, position, email, phone/WhatsApp |
| 6 | `sharing` (yes / profile only / no) | enum, see 4 |
| 7 | presence | `CPresence` rows, see 2 |
| 8 | `settings` (rural, informal settlements, …) | multi-enum |
| 9 | `populations` (women and girls, …) | multi-enum |
| 10 | `stages` (prevention … resilience) | multi-enum |
| 11 | `roles` | multi-enum, the **role list** |
| 12 | `hazards` | multi-enum, the list is still to agree (see questions) |
| 13 | `rolesWithSupport` | multi-enum, the same role list |
| 14 | `mechanisms` (task force, clusters, …) | multi-enum |
| 15 | `offers` | multi-enum, at most 3, the **exchange list** |
| 16 | `seeks` | multi-enum, at most 3, the same exchange list |
| 17 | `connectVia` (email, WhatsApp, HIVE, …) | multi-enum |

The lists live in one file, `espo/seed/data/cso-lists.json`, with codes (as the 5W's
`fivew-melissa.json`). The seed makes the enums from it and `kobo/forms/cso.py` makes the
forms' choices from it, so EspoCRM and Kobo always agree. "At most 3" is the form's
`count-selected(.) <= 3` constraint. "Other" is a text field next to each list.

The cholera roles (12 of them) are a second role list, `rolesCholera`. A form built for a
cholera mapping asks it in place of Q11/Q13 (`cso.py --cholera`), and EspoCRM keeps the
two in separate fields so neither list gets mixed into the other.

### 2. Where a CSO works: `CPresence` rows on admin areas

Q7 is a repeat in the form, "add a place": country, then province or state, then district
(each optional below the country), picked from `countries.csv` and `areas.csv` with a
`choice_filter` on the parent. Each row becomes a **`CPresence`** (organisation, admin area
at the deepest level given, the country), through `[[repeat]]`. A repeat is used, not
cascading select_multiples, because the bridge already takes rows and each row is one
place on the map.

**Admin areas for many countries.** `CAdminArea` gets a `country` (ISO3) and level
`admin0` for the country itself. A loader (`espo/seed/admin_areas.py`) imports a country's
boundaries list: the COD-AB from HDX where there is one (P-codes, as for Jamaica),
otherwise geoBoundaries (its own ids). Phase 2 loads the pilot countries only. All 194
countries at admin0 are small. Every district of every country is not small (tens of
thousands of rows), so the forms should be per country or per region, not one worldwide
`areas.csv`.

### 3. An operational update is a `CCsoUpdate`

The short form makes one record per submission:

| Q | Field |
|---|---|
| 1 | `organisation`, from the roster (see 5) |
| 2 | `adminArea` (country → province → district), `locality` (text), optional geopoint |
| 3 | `roles`, from the role list |
| 4 | `status`: `PLANNED`, `READY`, `ACTIVE`, `SUSPENDED`, `COMPLETED` |
| 5 | `populations` (the Q9 list), `facility` (text, optional) |
| 6 | `needs`, at most 3, from the exchange list (Q16's), `needsNote` |

It is a new entity, not the 5W's `CActivity`. That one is shaped by the Melissa form
(sector, its 84 activity types, people counted by group), and the CSO update counts
nobody. An update may link to a `CResponse` when it is about a declared emergency.
Without one, it is preparedness.

The latest update per organisation, place and role is the one that counts for the maps.
A formula marks older ones `superseded`, so the feeds read only current rows.

### 4. Who sees what: teams by country, and the CSO's consent

- **Teams by country.** A country team (`CSO: Jamaica`, …) for the WHO country office and
  its coordinators. A formula puts an organisation, its presence rows, focal points and
  updates in the team of every country it is present in, as tasks follow their projects
  in the 5W. A regional or global team sees several.
- **Consent (Q6) shapes the directory, not EspoCRM's own screens.** Coordinators see every
  profile, whatever the answer. What other CSOs and partners see comes through the
  dashboard's directory feed:
  - `yes`: profile and focal point contacts;
  - `profile only`: profile, no contacts (a formula fills `sharedContact` only for `yes`,
    and the feed reads that field, never `CFocalPoint`);
  - `no`: not in the directory, or in the matching view.

  EspoCRM's field security is per role, not per record, which is why the copy is made by a
  formula and not by access rules.

### 5. The roster and the link to the update form

The update form's Q1 is "select from roster". Listing every CSO by name on a public form
would show the names of those that said `no` to sharing. So:

- on its first profile submission a CSO gets its code (`ORG-`), and the focal point gets an
  email (Resend) with the code and a **prefilled link** to the update form
  (`…/x/<form>?d[/data/organisation]=ORG-…`). The update form takes the code from the link
  (or typed in) and the bridge links it by `lookup`;
- coordinators, who submit for several CSOs, use a version of the form with
  `organisations.csv` (`[[list]]`, filtered by their team).

### 6. Matching offers and needs: `CMatch`, made by a rules agent

Q15 (offers) and Q16 or update Q6 (needs) use the same exchange list. A match is the same
item offered by one CSO and sought by another, in a place they share.

- A scheduled agent (rules only, no model, as "5W: no report") runs each morning and makes
  a **`CMatch`** for each new pair: the CSO seeking, the CSO offering, the item, the admin
  area they share (the closest: district, then province, then country), and how the need
  was given (profile or update). Neither CSO can have `sharing = no`.
- A match has a status, `SUGGESTED` → `INTRODUCED` → `CONNECTED` or `DECLINED`, and goes in
  the country's team. The country coordinator gets a task when a need from an update has
  matches ("3 CSOs offer Logistics in Tete").
- The runner today filters records and makes tasks. Pairing two records is a new kind of
  rule, a `match` route (entity, the field on each side, the shared place), which is new
  code in `agents/`.

The matching view in the dashboard reads `CMatch`, so it shows the same pairs the
coordinators follow up, not ones of its own.

### 7. The four outputs in kobo-dash

All four read EspoCRM feeds, one feed user per country team (or region), current rows
only, no contacts except `sharedContact`.

1. **Directory**: a table of organisations (name, acronym, type, countries, roles, offers,
   `sharedContact`), searchable and filtered by country, type, role and population. Check
   that kobo-dash's table searches text. If it doesn't, that is a small kobo-dash change.
   Signed-in partners also have EspoCRM's own list view.
2. **Presence and reach**: a map of `CPresence` by admin area, coloured by the number of
   CSOs, filtered by setting (Q8) and population (Q9).
3. **Gaps and overlaps**: `CCsoUpdate` by district × role, for `READY` and `ACTIVE`. A gap is
   a district with a need for a role and no CSO active in it. An overlap is a district
   with more than N CSOs active in the same role.
4. **Matching**: `CMatch` by item and place, with their status.

The dashboards are designed through kobo-mcp's dashboard tools, with the feeds set up by
the EspoCRM MCP's `create_dashboard_feed`, as for the 5W.

### 8. Follow-up

- **"CSO: profile out of date"**: a scheduled agent, a task for the country coordinator
  when a profile hasn't been updated in 12 months (as "5W: no report", `idleDays`).
- **"CSO: update gone quiet"**: an `ACTIVE` update with nothing newer in 30 days.
- Data checks as flags: an update in a place outside the CSO's presence (add the presence
  or explain), or a role in an update that isn't in the profile.

## What stays out

- Charts and summed reports inside EspoCRM: the dashboard does them.
- A public directory open to anyone: the directory is for participating CSOs and
  authorised partners (Q6's own wording), behind kobo-dash's sharing.
- Registration checks on CSOs (are they real, are they registered where they say): that
  is WHO's process. EspoCRM holds the result as a `verified` flag if WHO wants it.
- Moving data into WHO HIVE: Q17 records that a CSO prefers it, nothing more.

## Phases

0. **Agree with WHO** (the questions below): pilot countries, the Q12 hazard list, the
   need list for update Q6, where it runs, the languages.
1. **The lists and the forms**: `cso-lists.json`, `kobo/forms/cso.py` making
   `cso-profile.json` and `cso-update.json` (and the cholera version), constraints,
   translations if agreed. A phone check of both forms on the test account.
2. **Admin areas for many countries**: `CAdminArea.country` and `admin0`, the loader (COD-AB,
   geoBoundaries), the pilot countries loaded, `countries.csv` and `areas.csv` on the forms.
3. **EspoCRM**: the profile fields on `COrganisation`, `CPresence`, `CCsoUpdate`, country
   teams and their formulas, `sharedContact`, `superseded`, the roles. Templates
   `cso-profile` and `cso-update`. Tests in `tests/cases/cso.py` (isolation between country
   teams, consent), and `connection.py` cases for both forms on real Kobo.
4. **The roster**: codes on the first profile, the email with the prefilled link, the
   coordinators' version of the update form.
5. **Matching**: `CMatch`, the runner's `match` route, the example agent (dry run first),
   tests in `agents.py`.
6. **Dashboards**: the four views on kobo-dash feeds.
7. **Follow-up** agents and data checks; a manual page ("CSO mapping") with screenshots
   from demo data in a pilot country.

## Risks and open questions

- **Q2 mixes kinds of type.** "National NGO" (reach) and "Women-led" or "Youth-led"
  (identity) aren't exclusive, but Q2 is select one. Suggest: Q2 select one for the main
  type (community-based, local, national or international NGO, network, academic, …), and a
  new select-all for identity (women-led, youth-led, organisation of persons with
  disabilities, faith-based, lived-experience).
- **Q12 has no options** in the draft. A candidate is the UNDRR/ISC Hazard Information
  Profiles at their top level, plus the priority diseases WHO wants named.
- **Update Q6's list** isn't given. The plan assumes Q16's exchange list, so needs and offers
  match. If WHO wants an operational gap list instead (supplies, staff, access, funding…),
  matching then needs a mapping between the two lists.
- **Q5 asks for one focal point.** Allow a second (a repeat, as the 5W's `FOCAL_POINTS`) so
  a profile doesn't go dark when one person leaves.
- **Where it runs and whose data it is.** Kobo-hosted, WHO-hosted or one per region decides
  who signs in, and the data protection terms for focal points' contacts. Sign-in for
  partners across countries wants OIDC (Phase 6 of the setup plan, not done).
- **Languages**: WHO's work wants at least English, French, Spanish, Arabic, Portuguese and
  Russian. Kobo forms take translations, and the lists file would hold labels per
  language. EspoCRM's labels for these fields need the same.
- **Volume** is small next to the 5W's: hundreds to a few thousand CSOs per region, with
  updates weekly at most. What's large is the admin areas (see 2).
- **Matching noise**: "Training or mentoring" offered by many and sought by many, all in one
  country, makes a lot of pairs. Match at district or province first, and at country only
  when nothing closer exists. Cap the suggestions per need (5) and order them by how many
  places the two CSOs share.

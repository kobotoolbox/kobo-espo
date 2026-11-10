# Workflow F: CSO mapping (Kobo and WHO)

Status: 2026-11-10, being built, Kenya the pilot country. From the **Draft CSO mapping
tool v1** (Kobo and WHO, `ref/Draft CSO mapping tool v1.docx`): a core profile of each
civil society organisation (17 questions) and a short operational update form (6
questions), shown through four dashboard outputs. It is built on what the 5W (Workflow E,
`workflow-e-5w-plan.md`) built.

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

**The pilot is Kenya**, built so that other countries can be added with either their own
forms or one generic form (see 2).

## What already exists

- Kobo → EspoCRM through the bridge: records matched by a code, links found by a code
  (`lookup`), **repeat groups** (`[[repeat]]`, one record per row), geopoints (to
  latitude/longitude fields), media.
- Lists from EspoCRM onto Kobo forms (`[[list]]`, CSV media), filtered by team.
- From the 5W: `COrganisation` (a list everyone reads, with codes), `CFocalPoint` (people's
  contacts, which viewers can't read), `CAdminArea` (P-code, level, parent P-code, country
  ISO3; one seed file per country, `espo/seed/data/admin-areas-<iso3>.json`), short codes
  (`_code.formula`), the "5W: no report" agent, data checks as flags.
- The agent runner: code tools (`agents/tools.py`) whose values a rule writes onto the
  record, scheduled agents, tasks.
- **The Humanitarian Geocoder** (`~/Desktop/work/repos/jamaica-geocoder`, running at
  `geocoder.kobolabs.dev`): OCHA COD-AB boundaries for 110 countries in PostGIS.
  - `GET /boundaries.geojson?country=KE&level=2`: polygons with `pcode`, `name` and their
    parents' P-codes and names (public);
  - `POST /reverse_geocode` (latitude, longitude, country): the P-codes of every level at
    that point (needs an API token, DRF `Authorization: Token …`);
  - `/xlsform`: a per-country form with cascading admin selects.

  **Kenya is there at admin1 (47 counties) and admin2 (290 sub-counties)**, P-codes
  `KE047` (Nairobi), `KE047288` (Kamukunji). No wards.
- **kobo-dash** (`~/Desktop/work/repos/kobo-dash`) reads EspoCRM through feeds (a
  read-only user per feed, limited to a team and the feed's fields, `espo-source-plan.md`
  steps 1–5 done and merged), with geo and select_multiple table kinds; **choropleths from
  uploaded boundary layers** (GeoJSON, the property holding the code); **tables with
  search**. A feed reads one entity: no joins between feeds (its plan's step 7).
- Email through Resend (access info, notifications, and anything the seed or an agent sends).

Not there: a CSO's profile, an update record of this shape, any matching, admin areas
outside Jamaica, `admin0`, P-coding from a geopoint, and the four dashboard views.

## Design

### 1. A CSO is a `CCso`, its profile

**Not `COrganisation`.** Everyone reads `COrganisation` (the 5W's list), and a CSO that
answers `no` to sharing (Q6) must not be listed to everyone. So the profile is its own
entity, `CCso`, read by its country teams (see 4), with an optional link to the 5W's
`COrganisation` when the CSO is also in a response's list.

The core form makes or updates the CSO, matched on its code (`CSO-`, given at the first
submission, see 5), so a CSO keeps one record however many times it updates its profile.
Its profile fields, one per question:

| Q | Field | Type |
|---|---|---|
| 1 | `name`, `acronym` | varchar |
| 2 | `csoType` | enum (14 types). Kept apart from the 5W's `orgType`, whose codes come from the Melissa form |
| 3 | `country` (where registered) | ISO3, enum of WHO member states |
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

Until WHO agrees them, the plan's suggestions are in the lists and marked as drafts in
`cso-lists.json` (`"draft": true`): a top-level hazard list for Q12 (asked), and the
identity list split out of Q2 (asked only with `cso.py --identity`, which also drops those
options from Q2: the forms keep WHO's Q2 as written until WHO chooses). Update Q6 uses
Q16's exchange list (see the questions). Countries (Q3, and the generic form's places):
the 193 UN member states, the Cook Islands, Niue and Palestine, by ISO3.

`cso.py` writes each form's **bridge template** with it (`kobo/templates/cso-*.toml`), so
a form and its template always agree: a country gets its forms by adding it to
`COUNTRIES` in `cso.py` (its admin levels' labels) and rerunning it.

### 2. Where: P-codes, from a form's cascade or from a geopoint

Every place in the CSO mapping ends as a **link to a `CAdminArea`** and its P-codes, so
teams, matching, feeds and the dashboard never care how the place was asked. Two ways of
asking, chosen per country:

- **A country's own form** (Kenya): a cascade, county → sub-county, from `areas.csv`
  (`select_one_from_file`, `choice_filter` on the parent), its P-codes the geocoder's.
  The bridge links the area by `lookup = "pcode"`, as for the 5W's parishes. An optional
  geopoint too.
- **The generic form** (any country without a form of its own): the country, then a
  **geopoint** ("drop a pin in each place you work"). The bridge writes the latitude and
  longitude; the **P-coding step** (3) fills in the area.

Q7 is a repeat in the form, "add a place", one row per place, each row a **`CPresence`**
(CSO, admin area at the deepest level given, its P-codes, country) through `[[repeat]]`.
A repeat, not cascading select_multiples, because the bridge already takes rows and each
row is one place on the map. A point is a poor answer for "where do you work" when a CSO
covers a whole county, so a country's form asks areas, and the generic form's pin is
taken as the sub-county (or the deepest level the country has) it falls in.

**Admin areas come from the geocoder.** `espo/seed/admin_areas.py <ISO2>` reads
`/boundaries.geojson` for each level and writes `admin-areas-<iso3>.json`, with level
`admin0` for the country itself (`CAdminArea.level` gains `admin0`). The seed loads every
such file, as it does Jamaica's. A country is added by running the loader (after the
geocoder has its boundaries) and the seed. Kenya: 1 + 47 + 290 areas. Every district of
every country is not small (tens of thousands of rows), so `areas.csv` on a form is
filtered to that form's country (`[[list]]` `where`).

### 3. The P-coding step

A `CPresence` or `CCsoUpdate` with a latitude and longitude and no admin area gets one:

- a code tool, `geocode`, in `agents/tools.py`, calls the geocoder's `/reverse_geocode`
  with the point and the record's country (ISO3 to the geocoder's ISO2), and returns the
  P-code of each level;
- two scheduled rules agents, "CSO: P-code the places" and "CSO: P-code the updates" (no
  model, `agents/setup/examples.json`), run it every hour on records with
  `pcodeStatus = pending` and write the P-codes; a formula links `adminArea` to the
  deepest one found (`record\findOne` by `pcode`). The geocoder down, the record stays
  `pending` for the next hour;
- a point outside the country's boundaries is `pcodeStatus = outside`, a data check flag.

It runs after the record is in EspoCRM, not inside the bridge: the shared bridge needs no
geocoder, and a geocoder outage doesn't stop submissions. The geocoder's API token is
`GEOCODER_TOKEN` in `secrets/agents.secrets`.

### 4. An operational update is a `CCsoUpdate`

The short form makes one record per submission:

| Q | Field |
|---|---|
| 1 | `cso`, by its code (see 5) |
| 2 | `adminArea` (county → sub-county, or a geopoint, see 2), `locality` (text), optional geopoint |
| 3 | `roles`, from the role list |
| 4 | `status`: `planned`, `ready`, `active`, `suspended`, `completed` |
| 5 | `populations` (the Q9 list), `facility` (text, optional) |
| 6 | `needs`, at most 3, from the exchange list (Q16's), `needsNote` |

It is a new entity, not the 5W's `CActivity`. That one is shaped by the Melissa form
(sector, its 84 activity types, people counted by group), and the CSO update counts
nobody. An update may link to a `CResponse` when it is about a declared emergency.
Without one, it is preparedness.

**Superseded.** The latest update of a CSO in a place is the one that counts for the
maps: a newer update from the same CSO for the same admin area marks the older ones
`superseded` (formula), whatever their roles. An update lists every role the CSO has
there now, so a role left out of the newer one is no longer current. The feeds read only
current rows.

### 5. Who sees what: teams by country, and the CSO's consent

- **Teams by country.** A country team (`CSO: Kenya`, …) for the WHO country office and
  its coordinators. A formula puts a CSO, its presence rows, focal points and updates in
  the team of every country it is present in (and its country of registration, and the
  other countries it names), as tasks follow their projects in the 5W. A country's team is
  found by name, `CSO: ` and its admin0 area's name (EspoCRM's teams take no custom
  fields), so a country needs its admin areas loaded and its team made; a CSO in no such
  country is in `CSO: Unassigned`. A regional or global team sees several. Role `CSO
  Coordinator`: CSOs, places, updates, focal points (later matches), read and edit in
  team. The tests' second country is Uganda (`CSO: Uganda`, its areas to admin2).
- **A profile sent again** (a new submission matched on the code) makes the places and
  focal points of the submission before no longer `current`: the new submission's rows
  are the CSO's now. The bridge keys a repeat's rows by submission, so without this the
  old rows would stay.
- **Consent (Q6) shapes the directory, not EspoCRM's own screens.** Coordinators see every
  profile, whatever the answer. What other CSOs and partners see comes through the
  dashboard's directory feed:
  - `yes`: profile and focal point contacts;
  - `profile only`: profile, no contacts (a formula fills `sharedContact` only for `yes`,
    and the feed reads that field, never `CFocalPoint`);
  - `no`: not in the directory, or in the matching view (`listed = false`, the feed's
    filter).

  EspoCRM's field security is per role, not per record, which is why the copy is made by a
  formula and not by access rules.

### 6. The code and the link to the update form

The update form's Q1 is "select from roster". Listing every CSO by name on a public form
would show the names of those that said `no` to sharing. So:

- on its first profile submission a CSO gets its code (`CSO-` and 4 characters, as the
  other short codes) and a **key** (`updateKey`, 16 random characters, never shown on a
  list). The focal point gets an email (Resend) with a **prefilled link** to the update
  form (`…/x/<form>?d[/data/cso]=CSO-…&d[/data/key]=…`). The bridge links the CSO by
  `lookup`. An update without the key (`keyCheck = missing`, the code typed) or with a
  wrong one (`wrong`) is kept and flagged, but doesn't count on the maps or supersede
  anything until a coordinator sets it `confirmed`. A guessed code isn't enough to report
  for a CSO, and a CSO that typed its code isn't lost;
- the profile form's own link has the code and key too, so a CSO updating its profile
  updates its record, not a new one. A profile with the code and no key (or a wrong one)
  is refused (API script), recorded on the connection with its reason;
- coordinators, who submit for several CSOs, use a version of the form with `csos.csv`
  (`[[list]]`, filtered by their team, no key needed: the coordinator's form is shared
  only with them).

### 7. Matching offers and needs: `CMatch`, made by a rules agent

Q15 (offers) and Q16 or update Q6 (needs) use the same exchange list. A match is the same
item offered by one CSO and sought by another, in a place they share.

- A scheduled agent (rules only, no model, as "5W: no report") runs each morning and makes
  a **`CMatch`** for each new pair: the CSO seeking, the CSO offering, the item, the admin
  area they share (the closest: sub-county, then county, then country), and how the need
  was given (profile or update). Neither CSO can have `sharing = no`.
- A match has a status, `SUGGESTED` → `INTRODUCED` → `CONNECTED` or `DECLINED`, and goes in
  the country's team. The country coordinator gets a task when a need from an update has
  matches ("3 CSOs offer Logistics in Kamukunji").
- The runner today filters records and makes tasks. Pairing two records is a new kind of
  rule, a `match` route (entity, the field on each side, the shared place), which is new
  code in `agents/`.

The matching view in the dashboard reads `CMatch`, so it shows the same pairs the
coordinators follow up, not ones of its own.

### 8. The four outputs in kobo-dash

All four read EspoCRM feeds, one feed user per country team (or region), current rows
only, no contacts except `sharedContact`. **A feed reads one entity**, so what a view
needs from another record is copied onto the row by formula: a `CPresence` and a
`CCsoUpdate` carry the CSO's name, type, settings and populations, and the P-code of each
level (`pcode1`, `pcode2`), so each view is one feed.

The boundary layers for the choropleths are the geocoder's GeoJSON (Kenya's counties and
sub-counties), uploaded to the dashboard with `pcode` as the code property.

1. **Directory**: a table of `CCso` (name, acronym, type, countries, roles, offers,
   `sharedContact`), `listed` only, searchable (kobo-dash's table search), filtered by
   type, role and population.
2. **Presence and reach**: a choropleth of `CPresence` by sub-county (`pcode2`), shaded by
   the number of CSOs, filtered by setting (Q8) and population (Q9).
3. **Gaps and overlaps**: `CCsoUpdate` by sub-county × role, for `READY` and `ACTIVE`. A
   gap is a sub-county with a need for a role and no CSO active in it. An overlap is a
   sub-county with more than N CSOs active in the same role.
4. **Matching**: `CMatch` by item and place, with their status.

The dashboards are designed through kobo-mcp's dashboard tools, with the feeds set up by
the EspoCRM MCP's `create_dashboard_feed`, as for the 5W.

### 9. Follow-up

- **"CSO: profile out of date"**: a scheduled agent, a task for the country coordinator
  when a profile hasn't been updated in 12 months (as "5W: no report", `idleDays`).
- **"CSO: update gone quiet"**: an `ACTIVE` update with nothing newer in 30 days.
- Data checks as flags: an update in a place outside the CSO's presence (add the presence
  or explain), a role in an update that isn't in the profile, a point outside the
  boundaries, a wrong key.

## What stays out

- Charts and summed reports inside EspoCRM: the dashboard does them.
- A public directory open to anyone: the directory is for participating CSOs and
  authorised partners (Q6's own wording), behind kobo-dash's sharing.
- Registration checks on CSOs (are they real, are they registered where they say): that
  is WHO's process. EspoCRM holds the result as a `verified` flag if WHO wants it.
- Moving data into WHO HIVE: Q17 records that a CSO prefers it, nothing more.
- Wards in Kenya: the geocoder has none. Sub-county is the finest level.

## Phases

Built (2026-11-10, not yet committed): Phase 1 (lists, `cso.py`, the four forms deployed
and compiled on the test account), Phase 2 (`admin_areas.py`, Kenya and Uganda), Phase 3's
entities, formulas, team, role, templates and `tests/cases/cso.py`, Phase 4's `geocode`
tool (unit tests, and live: Kamukunji, Kampala to admin3, Paris outside) and agents, the
staging droplet seeded. `tests/cases/cso.py` **39/39** on staging with a fake Kobo. The
geocoder's token is `GEOCODER_TOKEN` in `secrets/agents.secrets` (the tool reads it there
or from the environment). Next: the forms on real Kobo (`cso.py --kobo real`), then
Phase 5; the workflow packs (`workflow-packs-plan.md`) before Phase 5.

0. **Agree with WHO** (the questions below): pilot countries after Kenya, the Q12 hazard
   list, the need list for update Q6, where it runs, the languages. Building goes ahead on
   the draft lists meanwhile.
1. **The lists and the forms**: `cso-lists.json`, `kobo/forms/cso.py` making, for a
   country with its own form, `cso-profile-<iso3>.json` and `cso-update-<iso3>.json`, and
   for the rest `cso-profile.json` and `cso-update.json` (geopoint), and the cholera
   version (`--cholera`); constraints. A phone check of the forms on the test account.
2. **Admin areas from the geocoder**: `CAdminArea.level` `admin0`, `espo/seed/admin_areas.py`,
   Kenya's file, the seed loading it.
3. **EspoCRM**: `CCso`, `CPresence`, `CCsoUpdate`, the team `CSO: Kenya` and the role `CSO
   coordinator`, their formulas (teams, codes and keys, `sharedContact`, `listed`,
   `superseded`, copied fields, area from the deepest P-code), templates `cso-profile`
   and `cso-update` (Kenya's) and the generic ones. Tests in `tests/cases/cso.py`
   (isolation between country teams, consent, superseded, key), and `connection.py` cases
   for the forms on real Kobo.
4. **P-coding**: the `geocode` tool, the "CSO: P-code the point" agent, tests with the
   geocoder (and a fake one for the unit tests).
5. **The code and the link**: the email with the prefilled link, the coordinators' form.
6. **Matching**: `CMatch`, the runner's `match` route, the example agent (dry run first),
   tests in `agents.py`.
7. **Dashboards**: Kenya's boundary layers, the four views on kobo-dash feeds.
8. **Follow-up** agents and data checks; a manual page ("CSO mapping") with screenshots
   from demo data in Kenya.

## Risks and open questions

- **Q2 mixes kinds of type.** "National NGO" (reach) and "Women-led" or "Youth-led"
  (identity) aren't exclusive, but Q2 is select one. The draft lists: Q2 select one for the
  main type (community-based, local, national or international NGO, network, academic,
  …), and a new select-all for identity (women-led, youth-led, organisation of persons
  with disabilities, faith-based, lived-experience).
- **Q12 has no options** in the draft. The draft list: the UNDRR/ISC Hazard Information
  Profiles at their top level, plus the priority diseases WHO wants named.
- **Update Q6's list** isn't given. The plan uses Q16's exchange list, so needs and offers
  match. If WHO wants an operational gap list instead (supplies, staff, access, funding…),
  matching then needs a mapping between the two lists.
- **Q5 asks for one focal point.** The form allows a second (a repeat, as the 5W's
  `FOCAL_POINTS`) so a profile doesn't go dark when one person leaves.
- **Where it runs and whose data it is.** Kobo-hosted, WHO-hosted or one per region decides
  who signs in, and the data protection terms for focal points' contacts. Real Kenyan CSO
  contacts wait for that answer: the staging droplet holds test data only. Sign-in for
  partners across countries wants OIDC (Phase 6 of the setup plan, not done).
- **Languages**: WHO's work wants at least English, French, Spanish, Arabic, Portuguese and
  Russian. Kobo forms take translations, and the lists file would hold labels per
  language. EspoCRM's labels for these fields need the same. Kenya: English (Swahili if
  WHO Kenya wants it).
- **Jamaica's P-codes aren't the geocoder's.** The 5W loaded Jamaica's areas from the
  Hurricane Melissa form: 14 parishes (3 numbered differently from COD-AB's, e.g. our
  Kingston `JM17`) and 775 communities directly under them (`JM01001`). The geocoder has
  COD-AB's 14 parishes, 131 areas between, and 775 communities as `JM010101`: no code in
  common below the parishes. A Jamaican pin would get codes EspoCRM doesn't have. Before
  CSO mapping in Jamaica: keep both schemes (tagged by source) or map Melissa's to COD-AB's.
- **Which countries' areas to load.** Not every level of the geocoder's 110 countries
  (tens of thousands of records, written one at a time, and every form's list). Suggested:
  every country's admin0 row (a pin lands in its country, a country team is then just
  `CSO: <name>`), lower levels only for pilot countries (`admin_areas.py <country>`).
- **The geocoder is a dependency** of the generic form: down, points wait as `pending`
  and are P-coded on the next run. Its boundaries are COD-AB's, and a country's P-codes
  can change with a new COD-AB edition: the loader's rerun updates the areas, and the
  records keep the P-codes they were given.
- **Volume** is small next to the 5W's: hundreds to a few thousand CSOs per region, with
  updates weekly at most. What's large is the admin areas (see 2).
- **Matching noise**: "Training or mentoring" offered by many and sought by many, all in one
  country, makes a lot of pairs. Match at sub-county or county first, and at country only
  when nothing closer exists. Cap the suggestions per need (5) and order them by how many
  places the two CSOs share.

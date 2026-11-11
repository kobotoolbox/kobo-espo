# The 5W's organisations: Accounts, their people, clusters' people and a portal

Status: 2026-11-11, a plan, checked against the UNDAC Handbook (8th ed., 2024: A.3
humanitarian coordination and the cluster approach, G.6 inter-cluster coordination, F IM
products; in ../undac-simex). It follows the CSO mapping's model (plans/cso-mapping-plan.md), which
already works this way, and builds on the formula traits (plans/workflow-packs-plan.md,
phase 3). Changes the `fivew`, `responses` and `core` packs.

**The 5W and the CSO mapping are separate projects, on separate instances** (2026-11-11):
the 5W is humanitarian response coordination (a response's OCHA, clusters and partners);
the CSO mapping is WHO's, standing, with its own users, data protection and lifecycle. They
share the *model* (an organisation is an Account, its people Contacts, a portal) and the
code (core, the traits, the bridge), not records. So nothing here links a 5W organisation
to a CSO profile; staging has every pack only to test them.

## Why

The 5W and the CSO mapping track the same thing: **which organisations work where, in
what, and who their people are**, then what they do. The CSO mapping does it with an
Account per organisation, its people as Contacts (several, changing, each active or not),
and a portal where the organisation keeps them current. The 5W does it with less:

- a responding organisation (`CResponder`) is one registration in one response, with
  **one** focal point as two text fields (name, phone) and the Contact the bridge makes
  from the email. It has an `account` link that nothing fills;
- an activity's focal points (`CFocalPoint`) are new records on every report: the same
  person reporting monthly is twelve records, and nobody knows they're one;
- the organisation can't see or correct what it reported; only the IM team can;
- clusters have a lead (a User) but no people of their own outside EspoCRM's users.

## The tiers: what is there, what's missing

As the UNDAC Handbook (8th ed., 2024; A.3, G.6) describes a response's coordination, and
where each tier is in EspoCRM:

| Tier (handbook) | Who | Needs | Today |
|---|---|---|---|
| HCT, RC/HC (A.3.1, p. 27) | heads of agencies, HC; OCHA its secretariat | the products: 3W, situation overviews | **the dashboard** (kobo-dash), not EspoCRM records |
| OCHA and the ICCG (A.3.3, p. 30; G.6, pp. 231-233) | OCHA (chair, IM), each cluster's coordinator and co-coordinator | the whole response: gaps and duplication across clusters | OCHA: **there** (the response's team, `Response: <name>`, is on everything in it). The cluster coordinators as a group: **missing** (§7) |
| Cluster or sector (A.3.4, pp. 30-31) | lead agency, government co-chair, coordinator, co-coordinator, IMO | their cluster's partners and activities | **there**: each activated cluster is a cluster project with its team (`Cluster: <response> WASH`); a registration is in every cluster it names, an activity in its cluster's. Its leadership and people: **missing** (§4) |
| Sub-national, area-based (A.3.4 p. 32; G.6 p. 233) | hub or area coordinators | one area's clusters and partners | **missing** (§8, later) |
| Cluster partners (A.3.4, p. 31: members' commitments) | the organisations, UN and non-UN, national and international | their own registrations, activities, people | **missing**: the portal (§5) |

So the cluster tier, and OCHA over the response, are how the 5W works already. The plan adds
the organisations' tier and the people at each tier, then the ICCG's shared view and, later,
the sub-national tier.

## Design

### 1. An organisation is an Account, once, across responses

The registration finds or makes the organisation's **Account** and links the
registration to it:

- found by its organisation in the list (`COrganisation`, the 5W's `ORG_` codes): an
  Account links to its `COrganisation`. One Account per listed organisation, whatever the
  response;
- "Other" (not in the list): an Account by its name, and the task the response's lead
  already gets to add it to the list (CActivity's formula does this today); once added,
  the Account takes the new list entry;
- each registration (`CResponder`) stays: it is the organisation **in a response**
  (its sectors there, its status, its last report). The Account is the organisation;
- an activity gets `account` (its registration's, else its lead organisation's
  Account): what the portal follows (§5).

**An Account's teams are the union of its registrations' teams**: an organisation in two
responses, or in two clusters of one, is seen by each through its own team. A new trait,
`teams_union`: the teams of the records that link to the Account (`CResponder.account`),
recomputed when one of them changes teams.

The CSO mapping's Account formula keeps setting its Account's teams from its CSO: on its
own instance nothing else writes them. On an instance with both packs (staging) an
organisation in both would have its teams written twice; the packs say so (a pack's
`conflicts`, the loader warning when both are applied) rather than sharing a formula.

### 2. Its people are Contacts, several, active or not

As the CSO's focal points:

- the registration form's focal point becomes a **repeat** (name, email, phone,
  position), each row a Contact on the organisation's Account, matched by email within
  that Account (the CSO profile's repeat matches by email within the CSO). This needs one
  thing in kobo-espo-bridge: a repeat's match on its parent record's *link*
  (`accountId = "@record.account"`), not only the record (`"@record"`);
- **Active** and **Shared** on Contact: the 5W's own (`cActive`, `cShared`, in the `fivew`
  pack), as the CSO pack has its own. The same pattern; moving both to `core` is worth it
  only when a third workflow needs them;
- a Contact takes its Account's teams (the inherit trait, with cascade): the response's
  coordinators and the clusters the organisation is in see its people, no one else;
- `focalPoint` and `focalPointPhone` on the registration go (migrated to Contacts).

### 3. An activity's focal points: the same Contacts

`CFocalPoint` stays, as **this person for this activity**: the report named them. Its
formula finds the Contact on the activity's Account (by email, else phone) or makes one,
and links it (`contact`). So:

- the person is one Contact, with every activity they were named in (a panel on the
  Contact: its focal point rows);
- a report names people as today; no bridge change for this part (the formula matches,
  not the template);
- it's a formula pattern worth a trait (`find_or_make_contact`): the CSO's repeat could
  use it too.

(My earlier answer suggested replacing CFocalPoint with a link to Contacts. Keeping it
as the link between a person and an activity is less work, needs no bridge change, and
keeps which report named whom.)

### 4. A cluster's leadership and people

The handbook (A.3.2-A.3.4, pp. 28-31; G.6 p. 231):

- clusters are **activated per response**, only those needed, on the HC's and HCT's
  decision; and deactivated later;
- each has a **Cluster Lead Agency**. At country level it's "the organisation best suited",
  not always the global lead or a UN agency;
- the affected **government should co-chair** each cluster "as far as possible, from capital
  to field" (a line ministry). National NGOs may co-lead too;
- in the **sector approach** the government leads and the UN agency co-leads: "the main
  difference between clusters and sectors lies in their leadership structure";
- each cluster has a **coordinator** (and a co-coordinator, if there is one). They make up
  the ICCG. Clusters also have their own IM people.

So a cluster project (`CProject`, one per activated cluster in a response) gets:

- **approach**: cluster or sector (who leads), and its status as activated, deactivated
  (today's Planning, Active, Closed, relabelled);
- **lead agency** and **co-leads**: Accounts, several co-leads (government line ministry,
  NGO). When the cluster is made, its lead agency is filled with the global lead as a
  suggestion (handbook fig. A.4: WASH UNICEF, Health WHO, Logistics and ETC WFP, Food
  Security WFP and FAO, Shelter IFRC and UNHCR, CCCM IOM and UNHCR, Protection UNHCR,
  Nutrition UNICEF, Education UNICEF and Save the Children, Early Recovery UNDP);
- **its people**: Contacts with their role in the cluster (coordinator, co-coordinator,
  IMO, government focal point), a many-to-many Contact ↔ CProject, for the people who don't
  sign in. The people who sign in stay **Users** in the cluster's team with the cluster
  roles (Cluster Lead, Cluster Partner, Cluster Viewer), a government co-chair as one of
  them.

The cluster's team and the response's see its people. Organisations see their clusters'
contacts in the portal (read only): who to call about WASH. The handbook lists a **contact
list** with the 3W among the IM products (B, p. 54): the response's contact list (by
cluster, by organisation) is an export of these Contacts and the organisations' (§2).

**The sectors list** (the Melissa form's) is a flat list of clusters, an AoR (Child
Protection) and a working group (Cash). It has no Logistics or CCCM, both global clusters
(fig. A.4). It gains them, and each entry a kind (cluster, area of responsibility under
Protection, working group). The handbook doesn't list the AoRs (Child Protection, GBV,
Mine Action, Housing, Land and Property): that's from the IASC's cluster arrangements, to
check with a real response's setup before it ships.

### 5. The organisation's portal

As the CSO portal: **register in Kobo, keep current in the portal**.

- An **Organisation portal** (`/portal/organisations`) in the `fivew` pack, a portal role
  at the "account" level (`aclDefs.<Entity>.accountLink = "account"`, installed with the
  KoboWorkflows extension as the CSO's are);
- what an organisation's people do there:
  - see its registrations (one per response) and correct its details (acronym, type,
    sectors); not the response, the key or the status;
  - see, add and correct its **activities** and their locations, for responses it's
    registered in. A new one takes their Account (the portal_default trait, from the
    Contact's `accountId`), its registration in the chosen response, and its project from
    the sector, as a Kobo report does. The data checks run the same; the IM team sees the
    flags and the changes in the stream;
  - keep its **people** current: add, change, mark inactive (as the CSO portal);
  - read its clusters' people (§4) and the response's basics (name, dates);
- a coordinator gives logins with the MCP's `invite_portal_user` (built: a Contact on an
  Account);
- the welcome email (the CSO's pattern, a pack parameter): a newly registered
  organisation's people get its registration code, the activity report's link with the
  response and organisation filled in, and the portal's address.

What it doesn't do: show other organisations. Who else works where is the dashboard's
(kobo-dash), not the portal's.

### 6. Reports still come from Kobo

Kobo stays the way organisations report in the field (offline, many at once). The portal
is for corrections, people, and organisations that prefer a screen. Both write the same
records with the same formulas.

### 7. The ICCG's shared view

The ICCG "tracks and monitors the response", across clusters, to find gaps and duplication
(G.6, pp. 232-233). So a cluster coordinator needs to see the other clusters' activities
too, read only, while editing only their own cluster's.

EspoCRM's roles can't say that: a role's "team" access applies to all of a user's teams, so
a coordinator in a second team for the ICCG could edit that team's records too. So:

- the ICCG's shared view is **the 5W dashboard** (kobo-dash): the response's 3W across
  clusters, its gaps and overlaps, read from a feed scoped to the response's team. This is
  also what the handbook means by a 3W (F, p. 183: a product, "to show the operational
  presence of partners by sector and location");
- in EspoCRM a coordinator works on their cluster's records only (as today);
- OCHA's people stay on the response's team, with edit access across it (as today).

### 8. Later: sub-national coordination

The handbook stresses area-based coordination: coordination at sub-national level, with
the ICCG "supporting sub-national level coordination groups" (A.3.4 p. 32; G.6 p. 233).
That's a tier by place: a hub's coordinators see the clusters' partners and activities in
their area (an admin1, or several).

It fits what's built: activities' locations have P-codes (the pcodes trait), and the CSO
mapping's teams by country are the same pattern. A hub is a team (`Hub: <response> <area>`),
and a record whose locations fall in the hub's areas is in its team (a trait,
`teams_from_areas`). Not in this plan's phases, as it needs real hubs to design against.

## Phases

1. **Accounts.** COrganisation ↔ Account; the registration's formula finds or makes the
   Account; `CActivity.account`, `CActivityLocation.account` (inherit); the `teams_union`
   trait on Account; a pack's `conflicts` (fivew, cso); a migration giving existing
   registrations their Accounts. Tests: fivew, isolation (an Account in two clusters is
   seen by both clusters' leads, not a third's; in two responses, by both responses'
   teams; the response team sees all).
2. **People.** `cActive`, `cShared` on Contact (fivew); the registration's
   focal points repeat (form, template; the bridge's `"@record.<link>"` match); Contacts
   take the Account's teams; the registration's text fields migrated. Tests: a person
   named again is the same Contact; a cluster lead sees the people of organisations in
   their cluster only.
3. **Activities' focal points.** CFocalPoint's `contact`, the `find_or_make_contact`
   trait; existing CFocalPoints matched to Contacts once. Tests: one person over several
   reports is one Contact.
4. **Clusters' leadership and people.** CProject's approach, lead agency (the global
   lead suggested), co-leads, its Contacts with their roles; the sectors list's kinds,
   Logistics and CCCM; the layouts; `create_project` (MCP) takes them. Tests: projects.
5. **The portal.** The Organisation portal and its role, aclDefs, the activity and
   location layouts for it, the welcome email. Tests: as CSO C10 (a portal user sees and
   edits their organisation's records only; makes an activity in their registration's
   project; can't see another organisation's).
6. **Manual and dashboards.** "The 5W" page: organisations, people, the portal, with
   screenshots; the 5W dashboard: the ICCG's 3W across clusters (§7) and the directory of
   organisations by cluster; the contact list export.

Each phase leaves every suite green: fivew, cso (unchanged), projects, isolation, connection (W7–W10),
mcp_people.

## Questions

- **One Account across responses.** I suggest yes: one organisation, one Account, one set
  of people, whatever response it's in; each response's people see it through their own
  teams. The alternative (an Account per response) is simpler and duplicates organisations
  and their people every response.
- **A tier above the response** (all of a country's responses, or the instance's): a
  "Coordination: <country>" team added to every response's teams there (the CSO mapping's
  country teams work this way), or Internal Staff as today. I suggest the team, made when a
  response is made for that country.
- **Can an organisation edit an activity once the IM team has checked it?** I suggest yes,
  with the change in the stream and the data checks run again; a "checked" status that
  locks it is a later option.
- **Keys on the activity report.** The CSO update form checks the CSO's key; the 5W report
  takes whatever organisation the form names. I suggest the same key check later, if
  misreporting shows up; not in this plan.

## Risks

- **Both packs on one instance.** Only staging has the 5W and the CSO mapping together; an
  organisation in both there has its Account's teams written by both. Tests keep their
  organisations apart; the loader warns.
- **Linking the two later.** A mapped CSO may become a response's partner (the handbook's
  localisation, G.4, and its local and national actors). That's an exchange between
  instances (an export, or an agent that proposes a registration), not shared records.
- **Matching people by email** misses phone-only rows (field reports often are): the
  fallback on phone helps; true duplicates remain for the IM team to merge (EspoCRM's merge).
- **Many teams on one Account** (an organisation in many clusters and responses): a
  Contact's teams are its Account's, which can grow long; fine for tens.
- **Portal users and Kobo**: a correction in the portal and a resubmission in Kobo can
  disagree; the latest save wins, and the stream shows both.

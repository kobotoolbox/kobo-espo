# Report: EspoCRM as request intake + response tasking hub, connected to KoboToolbox

Test of [plans/espo-kobo-setup-plan.md](plans/espo-kobo-setup-plan.md), 5 November 2026.
The user manual (with screenshots) is `site/`; the tests and their results are in `tests/`.

## Recommendation: go, for one instance

**One EspoCRM instance holds both workflows, with access kept apart by teams and roles.**
All isolation tests (T8–T13, T15, T16: 80 checks) pass, but only with three formula guards
added for gaps that EspoCRM's own permissions leave (below). The guards are in
`espo/formula/` and the seed reinstalls them. Conditions:

1. Keep the roles and formula scripts as tested. Non-staff roles read "team" or "own",
   never "all", except the shared standards.
2. Someone in several teams sees all of them. For a triager or a partner in two
   consortia that's by design. Give people only the teams they work on.
3. When someone leaves a response, reassign their open tasks. Closing a response does
   this for all of its tasks.
4. Administrators see everything, and fields, layouts and automations are instance-wide.
   Keep administrators few.

Choose a separate instance for a partner who needs their own administrator, or for data
that must stay on its own server, not for isolation between projects or responses.

**Remaining risks.**
- A misconfigured role (an "all" left on) exposes everything of that entity. Run
  `tests/cases/isolation.py` after any role change.
- EspoCRM upgrades could change the permission behaviour the guards rely on (collaborators,
  the assignment check). Rerun the isolation tests after each upgrade.
- The intake bridge's API key can read all cases, contacts and accounts, which it needs to
  find requesters and avoid duplicates. It's kept on the server only.
- Two bridges on the same template at once could both create a record for the same new
  submission: run one per template (or add the unique index, docs/manual-steps.md).

## Environment

| | |
|---|---|
| EspoCRM | 10.0.11 (`espocrm/espocrm:10.0.11-apache`), MariaDB 11.4.13, Caddy 2.10 (TLS), daemon container for scheduled jobs |
| Where | Throwaway droplet `espo-kobo-test` (DigitalOcean nyc1, s-1vcpu-2gb, 137.184.130.173), `https://staging.respond.kobolabs.dev` (A record in kobolabs.dev; `espo-test.kobolabs.dev` until 2026-11-08). Teardown: docs/manual-steps.md |
| Kobo | `kf.kobotoolbox.org` (production server), throwaway test account `bob_kobo`, its own projects named "... (espo-kobo test)" |
| Bridge | [kobo-espo-bridge](../kobo-espo-bridge) (stdlib Python 3.13, `python:3.13-slim`), one container per template, polling every 30 s |
| Advanced Pack | Not installed, here or on `espo.kobolabs.dev` (no modules beyond Crm): everything is core EspoCRM |

## Decisions and deviations from the plan

- **The existing `espo.kobolabs.dev` wasn't used.** It holds Josh's demo (a custom `CPerson`
  entity, a "Demo Kobo Intake API" user and role, 5 users). The plan says not to alter it,
  and this test needs instance-wide changes. A new throwaway droplet was public, so Kobo
  needed no tunnel. Replaying onto the real instance is `deploy/up.sh` + the seed + `deploy/bridges.sh`.
- **Delivery: polling (kobo-espo-bridge), not Kobo REST Services or KoboHooks** (plan §4.2;
  decided with Josh). Kobo's config is unchanged, and backfill and catching up after an
  outage come for free. So T2 and T3 test redelivery and outages through the bridge's
  ledger, not `retry_hook`/`get_hook_logs`. The bridge was extracted from
  `kobo-in-a-box/remote/espocrm` into its own repo and made general (any entity,
  requesters, matching, mentions, escalation, lists, media). kobo-in-a-box is unchanged
  until kobo-espo-bridge passes its own end-to-end tests there.
- **Kobo production server, test account** (Josh, 5 Nov), instead of staging. The scripts
  refuse a production URL unless `KOBO_TEST_ACCOUNT_ON_PRODUCTION=yes`, and touch only their
  own projects.
- **One API user per form, not one "Kobo Integration" role.** Each has only what its
  template needs, e.g. `kobo-volunteers` can't read cases.
- **`requestingOrganisation` is Case's own `account` link**, and the requester its own
  `contact`, rather than new custom links.
- **`koboSubmissionUuid` isn't unique in the database.** EspoCRM's field manager can't make
  a varchar unique. Idempotency is the bridge's lookup by uuid before creating, tested
  with lost ledgers and restarts.
- **Task statuses:** EspoCRM's own *Not Started / Started / Completed* are relabelled *To do /
  In progress / Done*, with *Backlog* and *Blocked* added. Replacing them would break
  EspoCRM's completed-date and "open" filters.
- **Workflow C (sites and lists) added** at Josh's request:
  - sites and installations registered from Kobo, with follow-up visits;
  - EspoCRM lists (sites, standards, responses) pushed onto Kobo forms as CSV media.
- **Media copied into EspoCRM** (plan §8.3 allowed links). Links to Kobo need a Kobo login,
  so copies are better. The approach follows kobo2logie's attachment handling.

## What EspoCRM did that the plan didn't expect

| Finding | Effect | What was done |
|---|---|---|
| "Team" assignment permission checks the assigner's teams, not the record's | A triager in two consortia could assign a Consortium A case to a Consortium B partner, who then sees it (T5 found it) | `Case`/`Task` API Before Save Scripts refuse an assignee or collaborator outside the record's team |
| Collaborators (v10) get read and stream only, not edit | A collaborator can't move the card; only the assignee can | Documented; "one assignee + collaborators" works for watching and commenting |
| Each assignee is added to collaborators and kept there | A reassigned task stays readable by its previous assignee, whatever their teams | Task formula drops the previous assignee on reassignment |
| "Own" access doesn't depend on teams | Someone taken out of a response still sees the tasks assigned to them (T13, T16) | Closing a response gives its tasks to the lead (CResponse formula); reassign when someone leaves |
| Assignment notifications only for Meeting, Call, Email by default | | Seed adds Case, Task, Response, Site |
| Mentions need the poster's role to have `mentionPermission`, and reach only users who can read the record | | Bridge roles get `mentionPermission`; the API user mentions by username without being able to list users |
| Duplicate check on create goes by name (409) | A second requester or volunteer with an existing name couldn't be created | The bridge matches by email itself and sends `X-Skip-Duplicate-Check` |
| v10 Docker: mounting all of `/var/www/html` ("legacy") doesn't install; installer open until installed | Scanners hit `/install/` within seconds | `data`, `custom`, `client/custom` mounted separately; Caddy waits for EspoCRM to be healthy |
| Formula: before-save scripts only (no after-save); a new record already has its id; reading an unset link-multiple on a new record is a 500 | | Starter tasks made in before-save; scripts read only set attributes |
| Links added to EspoCRM's own entities get a "c" prefix (`Task.cResponse`) | | Formulas and layouts use `cResponseId` |
| Saved filters are per user | No shared "board for response X" | Response page lists its tasks; manual step per person |
| Kobo: `kf…/api/v1/submissions` answers 410 | | Test submissions go to OpenRosa `kc…/submission`, as Collect and Enketo do |
| `python3 -I` ignores `PYTHONUNBUFFERED` | Bridge logs empty in Docker | `-u` |

## Test results

All on the droplet's EspoCRM; the JSON files have every check with its detail.

| Test | File | Checks | Result |
|---|---|---|---|
| T1–T7, T12, C1–C3 on real Kobo | `results/connection-real.json` | 72 | all pass |
| The same with the fake Kobo, plus Kobo down | `results/connection-fake.json` | 73 | all pass |
| T8–T11, T13, T15, T16 | `results/isolation.json` | 80 | all pass (after the guards above) |
| T14 | `results/workflow_b.json` | 8 | all pass |
| kobo-espo-bridge unit tests | `kobo-espo-bridge/tests` | 53 | all pass |
| T1 latency through the running bridges | `results/latency.json` | 5 | 4.4–26.4 s, mean 17.2 s (30 s polling) |

Per test (expected → actual):

- **T1** Support form → Case in its team, with name, category, priority, project, source,
  the requester's Contact and Account, the file copied as an attachment (same bytes; the
  other consortium's partner can't open it) → as expected; one pass, 4–26 s through the
  running bridge.
- **T2** Redelivery (lost ledger: full rescan) → still one case, one contact, one account; the
  requester's next request reuses their contact.
- **T3** EspoCRM stopped (`docker compose stop espocrm`), submission made, started again →
  the pass failed visibly (exit code, `status.json`), the next made the case once. Kobo down
  (fake): the same.
- **T4** A missing required answer and an invalid email → no case and no stray contact;
  each recorded in the ledger with its reason (`required answer missing: summary`,
  `HTTP 400 ... emailAddress`); the next submissions went through; no answers in the logs.
- **T5** Triager notified (mention); assigns to staff-1, who is notified; assigning to a
  user outside the case's team refused; a second team refused; an unassigned case escalated
  to the lead once, an assigned one not.
- **T6** Consortium A, B and internal requests → their own team; partner-a can't read B's case
  or B's partner account.
- **T7** Volunteer form → Contact, profile Volunteer, skills, availability, in the roster pool;
  not a user; signing up again (same email, other case) updates it; staff notified.
- **T8** Response 1 only (roster-1, volunteer-2): lists, records by id (their URLs), Kanban,
  global search and their own stream show nothing of Response 2 or the consortia; cases,
  contacts, accounts refused.
- **T9** Both responses (roster-2): the union, nothing more.
- **T10** Volunteer: user list = their team; assigning (in or out of the team), creating
  tasks, editing others' tasks refused. Roster: assigning within the team allowed, outside
  refused; a roster expert in both responses can't give a Response 1 task to a Response 2
  volunteer, or add them as collaborator.
- **T11** Partners: own consortium's cases, contacts, accounts only, by list or id; can't
  move a case to the other consortium.
- **T12** Each API key reads only its entities, lists no users, deletes nothing; the intake
  key can't edit cases.
- **T13** Removed from the team → refused at once, in an existing session (token). Own tasks
  stay readable (recorded, then handled by closing, T16).
- **T14** New response → its 4 starter tasks (its team, its lead, Backlog); the board filtered
  by the response shows them; a volunteer moves theirs; other responses' members see none.
- **T15** Roster moves own task; volunteer moves own task, not others'; collaborators read and
  comment but can't move (v10); no collaborator from outside the team.
- **T16** Closed and members removed → the response and all its tasks refused to them,
  including their former own tasks; staff still read them.
- **C1–C3** `responses.csv` and `standards.csv` on the registration form, `sites.csv` (that
  response's sites only, four columns) on the visit form; a registration makes a Site in its
  response's team with its photo (named as answered, though Kobo stores it cleaned up),
  linked to its Standard by the code picked, with the form's end time in UTC; a code with
  no Standard is recorded, no site made; again with the same code updates it; a visit sets status
  and last visit and adds a note with its photo, once; the list follows the new status; an
  unknown site code is recorded, not guessed.

## Automations with core EspoCRM only (plan Phase 5)

| Plan | How, without the Advanced Pack | Tested |
|---|---|---|
| New case → notify the triager | The bridge posts a note mentioning the route's `notify` users | T5 |
| Assignee notified; one team per case | EspoCRM's assignment notifications (Case added to the list); Case API Before Save Script | T5 |
| Unassigned for N hours → notify the lead | The bridge's `[escalation]` | T5 |
| New response → starter tasks | CResponse Before Save Custom Script (`record\create`) | T14 |
| Task assignment notifications | EspoCRM's own (Task added to the list) | T5, T14 |
| Email as well as in-app | EspoCRM's mention and assignment emails, through Resend | by hand (2026-11-09): an assignment email; `mcp_people.py` U4 the access info |

## Not done

- Phase 6 (OIDC via authentik/Auth0): optional, not started.
- Enketo/KoboCollect screenshots of the forms with lists: the test account's forms need a
  Kobo login. The lists were checked on the forms through the API.
- kobo-in-a-box's own end-to-end tests (60 checks on its rig) against the generalised
  kobo-espo-bridge, before the box switches.
- EspoCRM's portal for partners following their own requests.

## Candidates from kobo2logie for the bridge

Reviewed `~/Desktop/work/repos/kobo2logie`.
- **Taken:** media copying, which files and from where (`attachmentsToForward`,
  `isAllowedMediaHost`).
- **Already in the bridge:** conditional rules (`when`, routes) and backfill (polling
  from cursor 0).
- **Worth adding next**, as optional steps in a template:
  - write-back to Kobo of the case number and link ("response field injection", via
    KPI's bulk edit), with care that the bridge doesn't treat its own edit as a user's;
  - reverse geocoding of geopoints to P-codes (its self-hosted COD geocoder);
  - a PDF of the submission on the record (kobo2pdf).
- **Out of scope here:** AI transcription, extraction and validation. They fit as the same
  kind of optional step.

## Reviewed: kobo-connect (rodekruis)

[rodekruis/kobo-connect](https://github.com/rodekruis/kobo-connect) receives Kobo REST
Service webhooks and maps answers to EspoCRM with custom HTTP headers
(`question: Entity.field`).
- **Taken into kobo-espo-bridge:**
  - links by lookup: the record whose field has the answer, as its
    `Entity.link.field` headers do (`[[field]] type = "link"`, `entity`, `lookup`). Here the
    registration links the site to its Standard by the code picked. None or several: the
    submission is recorded, where kobo-connect skips the field;
  - datetimes: `type = "datetime"` stores Kobo's local time and offset in UTC, in the bridge
    (kobo-connect's docs have a formula and a hidden text field for it). Here the form's
    `end` becomes the site's "Registered";
  - attachment file names: Kobo stores `site photo (1).png` as `site_photo_1.png`.
    kf.kobotoolbox.org also gives the original (`media_file_basename`, checked on the test
    account), so it already worked here; older servers don't, and are now matched by the
    stored name.
- **Already in the bridge:** select-multiple (`multiEnum`), updating a record by a field
  (`match`; kobo-connect's search is `contains`, so `AB1` also finds `AB12`), skipping
  submissions (`when`), never twice (the ledger and the uuid, not a Cosmos DB), attachments
  (with a host check and a size limit), and lists for forms (CSV media, where its "linked
  Kobo" rewrites the other form's choices).
- **Not taken:** mapping a fixed index of a repeat group to a field (no form here needs
  repeats), several unlinked records from one submission (`[requester]` covers the linked
  case), webhooks instead of polling, lowercasing question names, its 121 and Bitrix24
  connections.

## Agents (MVP, 2026-11-05)

[The agents plan](plans/espo-agents-plan.md): agents set up as records in EspoCRM, run by
one runner (`agents/runner.py`, container `agent-runner`, `deploy/agents.sh`).

**Built.** Agent, Agent route and Agent run entities; the runner (triggers by stage or by a
watched field and a new note; rules before the model and after it; the model choosing a
route; actions as the agent's own API user; dry run); the model layer (`llm.py`: the output
schema from the Agent, code that fixes and checks the answer, sends errors back up to 2
times; the Claude API with structured output, adaptive thinking, the refusal fallback, web
search and fetch, PDFs; a fake model for the tests); code tools (`tools.py`: sanctions
against a fixture list, registry "not checked"); `sync.py` (an API user and a role made
from each Agent's setup, field by field); the guard formula on Application, Site and Task;
the Application entity with its board and the Grants review team (staff-2); three example
agents (`agents/setup/examples.json`: DD screening → DD research → review; site visit
triage), **in dry run** on the droplet.

**Tests.** `tests/cases/agents.py` 35/35 (fake model; 29 at first, W1–W4 with the schedule, E5 with the triage fix): triage E1–E5 (the
model reads every visit, a needs-repair one too; the safety rule overriding the model's "ok"; routine; no repeats; a danger the safety words miss, escalated by the model), dry
run, a version per change, the DD flow D1–D6 (clean, match, near miss, sent back, model
failing → failure route), sloppy output fixed in code, guards S1/S3, on a schedule W1–W4 (nothing before
switch-on, once per slot, the date condition). `agents/test_units.py` 14/14. After adding the agents: isolation 80/80, workflow B 8/8, connection 73/73 (fake Kobo).
Tests use their own agent copies in teams the examples don't work in, so the droplet's
runner never acts on test records.

**Found in EspoCRM 10.0.11.**
- A record can be assigned to an API user, and `env\userAttribute('id')` in an API
  before-save script names the API user: the guard identifies agents that way.
- Field-level security drops writes to read-only fields **silently** (no error). The agents'
  roles rely on it; S1 checks the values didn't change rather than for a refusal.
- An update with a stale `versionNumber` is accepted: no optimistic concurrency by default.
  Runs are claimed with Run records instead. (Worth telling Ponto, whose plan assumed it.)
- Once, a seed run got a 500 while saving a formula: a half-written route cache during the
  many rebuilds. Running the seed again fixed it.

**Not done yet** (plan status, top): draft mode, scenarios and gates, the Kobo application
form, a real registry and the real sanctions lists, export, an OpenAI-compatible provider,
the Agent Admin role, approving and rejecting by approvers only, manual pages beyond running
them. **No Claude API key on the droplet yet:** agents with a model fail their runs there and
take their failure route (in dry run, a note).

### Real models through Bedrock (2026-11-06)

No Anthropic key yet, so the examples ran on Claude through Amazon Bedrock, from a laptop
(Josh's AWS SSO login), against the droplet's EspoCRM with its runner stopped. New: provider
`AGENTS_LLM=bedrock` (`llm.py`), and `AGENTS_MODEL` to use another model than the Agent's
(Sonnet 5.5 for test runs). Records from `tests/agent-examples.py` ("BDR ..."). How to run it:
the manual, "Running it" → "Agents".

| Agent, record | Route | Opus 5.5 | Sonnet 5.5 |
|---|---|---|---|
| DD research, an application in Research | review | $0.025, 17 s | $0.009, 13 s |
| Site visit triage, a routine visit | ok | $0.005 | $0.0025 |
| Site visit triage, a broken well cover, children at the open hole | repair (rule, no model); after the fix, urgent_safety | | $0.003 |

- **The dossier is useful without web access**: it says what it couldn't check, flags a new
  organisation, and asks the applicant sensible questions.
- **Gap in the triage example, fixed the same day:** the "before" rule (status
  `needs_repair` → repair) took the route without the model, so a visit that was a danger
  to people got a routine repair task. The "after" safety rule's words (sick, injured,
  contaminated, ...) didn't catch "children leaning over the open hole" either. Now the
  model reads every visit: `repair` has no rule, and the instructions say a risk to people
  comes first whatever condition was chosen. The safety rule stays, as a backstop for the
  model. On Sonnet 5.5 the same visit went to urgent_safety, with the children at the open
  well as its reason. A rule that skips the model is safe only where the field alone
  settles it (DD screening's sanctions match), not where free text can say more.
- **Bedrock on Kobo's AWS account:** Bedrock's newer endpoint ("Mantle", the SDK's
  `AnthropicBedrockMantle`) serves Opus 5.5 but not Sonnet 5.5 or Haiku 5.5, so the
  provider uses bedrock-runtime with the `us.anthropic.` inference profiles (both models
  work there). Bedrock has no web search or fetch and no server-side fallback on refusals:
  DD research there works from the record alone.

### On a schedule (2026-11-06)

A third trigger next to "stage" and "change": **On a schedule**, every hour, day or week at
a time in UTC (Agent fields Repeats, At, On). At each time the agent takes every record that
fits its filter once (the run's key is the slot, `schedule:<time>`), optionally only those
whose date field is older than N days (`idleField`, `idleDays`). No catching up on times
before it was switched on; after the runner was down, the latest time it missed, once. The
example **Repair follow-up** (rules only, dry run on the droplet; its first time is Monday
2026-11-09 06:00 UTC): each Monday, a follow-up task for the response lead on each site
still marked needs repair with no visit for 7 days. A site that stays broken gets one every
week, by design: a reminder that it's still open. The tests move the runner's clock on
rather than wait (W1–W4).

## Kobo connections and one bridge service (2026-11-06)

Phases 0–2 of `plans/kobo-connections-plan.md`. kobo-espo-bridge's `bridge.py serve` runs
every connection in one process. A connection is either a template in `kobo/templates/`
or a **Kobo connection** record in EspoCRM (an admin pastes the template in). On the
droplet, the four bridge containers are now one, `bridge`. It does setup on the server,
as admin, when a template is new or changed and every 10 minutes, so `deploy/bridges.sh`
has no list of bridges and no setup loop. Each connection shows its status in its record:
Status, Last pass, Waiting, Waiting since and Last error. A connection made in EspoCRM
gets an API user of its own (`kobo-conn-<name>`).

- **Phase 0:** setup needs the admin password. EspoCRM refuses every admin call to an
  API user, whatever its role, and an API user changed to admin loses its key. Making an
  entity through the API works.
- **Tests:** connection 73/73 (fake Kobo) and 72/72 (kf.kobotoolbox.org) through `serve`; `tests/cases/serve.py` 8/8 (a
  connection made in EspoCRM runs in the next pass; a broken template; paused; edited).
- **Found in EspoCRM 10.0.11:** a field marked read-only is ignored by the API, for
  admins too. The status fields are ordinary fields, in panels labelled "written by the
  bridge".
- **Switching the droplet:** each container's state folder (ledger and cursor) was moved
  to the name `serve` uses (`intake` → `support-request`, ...). At the first try,
  `deploy/up.sh` had removed the old containers first, so the move was skipped and
  site-registration rescanned its 65 submissions with a new ledger. Nothing was written
  (7 found in EspoCRM already, 58 recorded as waiting). That ledger was dropped and the
  old one moved into place. `deploy/bridges.sh` now moves the state before the service
  starts.
- **Phase 3, a template from the form** (`propose.py`, 2026-11-06): for kobo-espo's
  forms, the proposal matches the hand-written templates but for three naming choices
  (`tests/test_propose.py`). A proposal for a form with every question type was set up
  and run as it was, and the record matched its preview exactly (serve.py K5, 12/12).
  Repeat groups, calculations and follow-ups have no default.
- **Phase 4, the EspoCRM MCP** (kobo-espo-bridge `espo_mcp/`, 2026-11-06): 14 tools and the
  prompt "Connect a Kobo form to EspoCRM", at `https://espo-test.kobolabs.dev/bridge/mcp`
  (Caddy routes `/bridge/*` to the `bridge-mcp` service). Admins only, a key each (hashes
  only on the server, checked against EspoCRM on every call); every change in two calls
  with a signed token for exactly what was shown; no delete; access at team level only.
  `test_connection` waits for the service's pass, so one process still polls each form.
  Tests: `tests/cases/mcp.py` 21/21 (the tools, a whole connection made from a form to a
  new entity), `tests/cases/mcp_http.py` 8/8 (over HTTP with the SDK's client: no key, a
  made-up key, a non-admin's key, another Host refused). The seed now keeps roles' access
  to entities it doesn't define (what `grant_access` gave). Not done yet: the acceptance
  run in Claude Code with kobo-mcp, from "I want a grant application form" to a record.
- **Phase 5, signing in** (2026-11-06, `espo_mcp/oauth.py`): claude.ai and Claude Desktop
  connect with the MCP's URL alone. The MCP is its own OAuth server (the SDK's routes);
  its sign-in page takes an EspoCRM admin's username, password and two-factor code,
  EspoCRM checks them (`/App/user`, its session ended at once), and they're kept nowhere.
  Tokens are sealed (AES-GCM), name the user, and every call and refresh checks the user
  is still an active admin. Caddy routes the two discovery documents clients look for at
  the site's root. Keys still work for Claude Code. Tests: `mcp_http.py` 20/20 (H5–H8:
  discovery; the SDK's OAuth client signing in; a wrong password, a non-admin, a forged
  form, an unregistered redirect refused; two-factor, PKCE, codes and refresh tokens used
  once; admin rights taken away). Live: signed in through Caddy and called the tools.
  Not done: the acceptance run in claude.ai.
- **Phase 7, the four templates as records** (2026-11-06): the droplet's bridge no longer
  reads `kobo/templates/`. `bridge.py serve adopt` turned each file's connection into an
  ordinary record, edited in EspoCRM (and with `update_connection`), under the same API
  user, and moved its state to the record's: the first pass after found nothing new, and
  the waiting counts were unchanged (16, 8, 3, 0). `deploy/bridges.sh` runs adopt on every
  `up`: a new droplet gets its four connections from the files, and after that the files
  are only the tests' fixtures. Tests: serve.py K6 (19/19 with K1–K5).
- **Phase 6, the manual** (2026-11-06): a "Connecting a form" page, linked from the
  overview, with an example conversation that is illustrative until the acceptance runs
  give a real one. The connection record showed its template as Markdown; now raw text.
- **Limits:** `kobo-edits` (edited submissions, cases only) is still one user for every
  Case template, so two Case connections would share its role. Still one bridge service
  per instance.

## Cluster projects (2026-11-08)

For a response that supports several clusters (Hurricane Melissa: ETC, WASH...), each with
its own team managing its sites and tasks.

- **A Cluster project** (`CProject`) belongs to a response and is in its own team and the
  response's (formula). Its sites and tasks take its teams; a team added to the project
  reaches them; closing it gives its tasks to its lead. The response's team is for its
  coordinators: they see every project, a project's people only theirs, and not the
  response record itself.
- **Roles:** Cluster Lead (sites and all the project's tasks), Cluster Partner (sites,
  tasks, their own tasks), Cluster Viewer (reads, posts notes). Internal Staff gets
  projects too.
- **Tasks on sites and cases:** Task's own Parent field now takes a Site
  (`updateLink`, so a Site has a Tasks panel). A task on a site goes into its project,
  response and teams; on a case, the case's team. The task guard now takes the team from
  the project, response, site or case, in that order.
- **Found:** EspoCRM lets people assign only those who share a team with them, so a
  coordinator in the response's team sees a project's tasks but can't give them to the
  project's people until they join its team. Kept that way, rather than widening
  coordinators' assignment to "all" with more guards. And with "team" assignment, a record
  sent with no team is refused (the UI always sends the default team).
- **Access is per person:** EspoCRM adds up a person's roles across all their teams, so a
  lead of one project who views another has lead access in both.
- **The EspoCRM MCP** sets it up: `list_projects`, `create_response`, `create_project`,
  `list_roles`, `invite_user`, `add_to_team`, `remove_from_team`, and a prompt, "Set up a
  response". Regular users only, never the bridge's or agents' roles (any role an API user
  holds), each change confirmed. `invite_user` never handles a password: EspoCRM emails a
  set-your-password link (`sendAccessInfo`) when outgoing email is configured (it is
  since 2026-11-09: see "Email" below).
- Tests: `tests/cases/projects.py` 44/44, `tests/cases/mcp_people.py` 24/24; isolation
  80/80, workflow B 8/8, agents 35/35 unchanged.
- **A bridge bug found on the way** (kobo-espo-bridge): escalation and the status sync to
  Kobo took every Kobo record of the entity, not only the connection's own forms'. With two
  Case connections, each escalated the other's cases (with its own routes) and pushed their
  statuses. Seen as T5 failing: the droplet's support connection escalated the tests' cases
  first. Both now take only the records of the connection's forms (unit test extended).
- **Next:** Workflow E, the response's 5W (`plans/workflow-e-5w-plan.md`).

## Workflow E: the response's 5W, on the Hurricane Melissa form (2026-11-08)

Plan: `plans/workflow-e-5w-plan.md`. Built on the real Melissa 5W form (v1.9, `ref/`),
with its codes; our form is made from it (`kobo/forms/melissa.py`).

- **Organisations** are a list (`COrganisation`: the form's 137, `ORG_` codes and types),
  put on the forms by EspoCRM and filtered by type as the Melissa form does; one typed in
  becomes a task to add it. Organisations can also **register** for a response and its
  sectors (`CResponder`), which puts them in those sectors' projects' teams.
- **An activity** (a submission) goes to its response's project for its sector, and its
  teams. **Each community row** of the form's repeat is an `CActivityLocation` (parish and
  community by P-code, people by group × women, men, children, targeted and reached); the
  activity keeps the totals. **Focal points** are their own records, which viewers can't read.
- **Repeat groups in the bridge** (`[[repeat]]`): a record per row, matched by submission
  and row on a retry, rows a shorter version lost removed, a row that fails recorded with
  its number while the rest stay.
- **Short codes** (RSP-, PRJ-, REG-, ACT-, TSK-, APP-) are Kobo lists' choice names.
- **Found:** Jamaica's P-codes are not ISO's order: JM17 is Kingston, JM08 St. Andrew,
  JM01 Clarendon (and there are no JM03, JM05, JM06). The first draft had them wrong; the
  seed now takes the 14 parishes and 775 communities from the Melissa form and removes the
  rest. EspoCRM's API pages at 200 records at most.
- **Follow-up (2026-11-09):** the agent "5W: no report" makes one task per silent
  organisation (a week without a report, or never), and data checks flag figures that
  don't add up, without refusing the report. On real Kobo the 5W forms passed 86/86.
- The 5W dashboard is kobo-dash's, with EspoCRM as a source (kobo-dash
  `plans/espo-source-plan.md`); its step 1 (map-point and multi-choice table columns) is
  done there (branch `espo-source`, 845 tests).

## Email (2026-11-09)

The droplet's EspoCRM sends with Resend: `noreply@respond.kobolabs.dev`, "Kobo Respond",
SMTP `smtp.resend.com` port 2587 with TLS (DigitalOcean blocks 465 and 587), a send-only
API key. Assignment emails (tasks, cases, applications, projects, responses, sites) and
mention emails are on, so the bridge's notes that mention people go by email too.

- **Found:** this EspoCRM doesn't send its own emails with the SMTP settings of
  Administration → Outbound Emails. Access info and notifications go through the group
  email account whose address is the from address (active, SMTP on); without one, "No
  system SMTP settings" in the log while the page's "Send Test Email" works. The MCP's
  `invite_user` now checks for that account (`email_ready`), not the settings.
- **Test addresses** are Resend's test inbox, `delivered+<username>@resend.dev` (the
  seed's users and `mcp_people.py`'s invited partner): nothing bounces off `example.org`.
  Contacts and focal points keep `example.org`: EspoCRM never emails them.
- `espo/seed/seed.py` sets it all up when `secrets/resend.key` (the key) is there; the
  steps by hand, for a real instance: `docs/manual-steps.md`, "Outgoing email".

## Open questions for Josh

1. **The real instance:** apply this to `espo.kobolabs.dev`, alongside its demo, or start a
   clean one? It needs the seed's instance-wide changes (entities, Task statuses, roles).
2. **A dedicated Kobo account for the bridge** (not a person's), with the forms shared to it.
   Which server: the global one, or the EU one for EU partners?
3. ~~**SMTP** for email notifications and invitations.~~ Done 2026-11-09 on the droplet:
   Resend, `noreply@respond.kobolabs.dev` (see "Email").
4. **Partners:** do they log in (as here, Partner Staff users), or only submit, or follow
   their own requests in EspoCRM's portal?
5. **Escalation time** and who it goes to, per project.
6. **Collaborators who can't move cards** (v10): acceptable, or should roster tasks be
   editable by the whole response team ("edit: team" for Roster Expert)?
7. **kobo-espo-bridge's home:** a repo under kobotoolbox on GitHub? And when should kobo-in-a-box
   switch to it?
8. **Teardown:** when to delete the droplet and DNS record, and the test projects on the
   Kobo account?
9. ~~**Site visit triage and danger to people.**~~ Done 2026-11-06: the model reads every
   visit (Bedrock results above).

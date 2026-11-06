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
| Where | Throwaway droplet `espo-kobo-test` (DigitalOcean nyc1, s-1vcpu-2gb, 137.184.130.173), `https://espo-test.kobolabs.dev` (A record in kobolabs.dev). Teardown: docs/manual-steps.md |
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
| Email as well as in-app | EspoCRM's mention and assignment emails, once SMTP is set up | not tested (no SMTP) |

## Not done

- Phase 6 (OIDC via authentik/Auth0): optional, not started.
- Enketo/KoboCollect screenshots of the forms with lists: the test account's forms need a
  Kobo login. The lists were checked on the forms through the API.
- kobo-in-a-box's own end-to-end tests (60 checks on its rig) against the generalised
  kobo-espo-bridge, before the box switches.
- Email notifications (no SMTP on the droplet); EspoCRM's portal for partners following
  their own requests.

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

## Open questions for Josh

1. **The real instance:** apply this to `espo.kobolabs.dev`, alongside its demo, or start a
   clean one? It needs the seed's instance-wide changes (entities, Task statuses, roles).
2. **A dedicated Kobo account for the bridge** (not a person's), with the forms shared to it.
   Which server: the global one, or the EU one for EU partners?
3. **SMTP** for email notifications: which sender?
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

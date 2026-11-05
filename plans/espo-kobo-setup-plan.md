# Plan: EspoCRM as request intake + response tasking hub, connected to KoboToolbox

Audience: a Claude Code agent working with Josh Beretta (Kobo). Work through the phases in order, tick the boxes, and write findings to `REPORT.md` as you go.

## 1. Goal

Prove on **one EspoCRM instance** that we can run two workflows without a new instance per project or response:

- **Workflow A, support/request intake.** A KoboToolbox form submission creates a Case in Espo, notifies a triager, who assigns it to someone else to work on. Must work for an internal-only project and for multi-organisation projects (Kobo plus 3 or 5 partner orgs).
- **Workflow B, humanitarian response tasking.** A "Response" (e.g. an earthquake response) has its own team. Internal staff, roster experts and volunteers are given tasks on a board, with access limited to that response. This replaces the IFRC SIMS pattern of GitHub Projects, without requiring GitHub accounts.

Success means the Kobo-to-Espo connection is tested end to end and the access-isolation model is shown to hold (see section 9).

## 2. Decisions already made (do not re-litigate)

- Single Espo instance. Isolation comes from **Teams + Roles**, not separate instances. If isolation tests fail, report that and recommend per-project instances. Do not silently work around it.
- **Portal users cannot be assigned records** (Espo design: assignment permission is forced to "no" for portal users). Therefore volunteers, roster members and internal staff who must receive tasks are **regular users with restrictive roles**. Portals are only for external orgs that submit and track requests.
- A Case can be assigned to multiple teams by default. Keep it to one team per case (use a workflow or formula, see Phase 5).
- Task board: Kanban on the Task entity needs an **enum status field** (Administration > Entity Manager > Task > Status field). It is one board per entity, so we filter by Response, not one board per response.
- Use the **Collaborators** option on Task for multi-person tasks (the Espo developer prefers one assignee plus collaborators over multiple assignees).
- Auth: start with Espo's built-in login. OIDC via a bridge (Auth0 or authentik) is a later, optional phase.

## 3. Inputs and rules of engagement

Ask Josh for anything missing here before Phase 2. **Never write secrets into files that get committed**; use environment variables or a `.env` that is gitignored.

Needed inputs:
- [ ] Espo target: URL, version, admin access method (or confirm we build in local Docker first). **Default: build and test in local Docker, then apply to the real instance only after Josh approves.**
- [ ] Is the **Advanced Pack** (Reports, Workflows, BPM) installed or licensed? This decides Phase 5.
- [ ] Which Kobo environment to use. **Use the Kobo staging server and a throwaway test project only.** The `Kobo_MCP_Staging` tools are available (`deploy_form`, `create_hook`, `get_hook_logs`, `retry_hook`, `create_submissions`, `get_submission`, etc.). Do not touch production projects.
- [ ] Where Josh's existing **KoboHooks** webhook proxy lives and how it is deployed. Ask. Do not assume.
- [ ] Is the Espo instance reachable from the public internet? Kobo's REST service must be able to reach it (or the proxy must).

Rules:
- Do not delete or alter anything on the real Espo instance or any production Kobo project without explicit approval.
- Prefer reproducible configuration (files in git) over clicking in the UI. If something can only be done in the UI, document the exact steps in `docs/manual-steps.md`.
- Check current behaviour against https://docs.espocrm.com before relying on anything below. Details here come from forum posts and docs summaries and may be out of date for your Espo version.

## 4. Repository layout

```
espo-kobo/
  README.md
  REPORT.md                 # running findings, decisions, test results
  docker-compose.yml        # espocrm + mariadb (+ daemon), local only
  .env.example
  espo/
    custom/                 # metadata and layouts for custom entities/fields (git-tracked)
    seed/                   # scripts to create teams, roles, users, test data via API
  kobo/
    forms/                  # XLSForms: support-request.xlsx, volunteer-availability.xlsx
    mapping/                # Kobo field -> Espo field mappings (JSON/YAML)
  proxy/                    # mapping/relay code if needed (see Phase 4)
  tests/
    run_all.sh
    cases/                  # one script per test in section 9
  docs/manual-steps.md
```

## 5. Phase 1: Environment

- [ ] Stand up Espo + MariaDB with Docker Compose (official `espocrm/espocrm` image; include the daemon/cron container so scheduled jobs run). Pin the version and record it in `REPORT.md`.
- [ ] Create an admin user. Confirm login works.
- [ ] Confirm the REST API responds at `/api/v1/` using an API user (Phase 3).
- [ ] Expose the local instance to Kobo staging for testing via a tunnel if needed (record which tool; tear it down afterwards).
- [ ] If Josh wants this on his real instance, repeat only after sign-off, ideally by replaying the git-tracked config.

## 6. Phase 2: Data model and access control

**Teams**
- [ ] `Internal Kobo` (staff).
- [ ] `Project: Consortium A (Kobo + 3 orgs)` and `Project: Consortium B (Kobo + 5 orgs)` as test teams for Workflow A.
- [ ] `Response: Test EQ 1` and `Response: Test EQ 2` as test teams for Workflow B.

**Roles** (set Administration > Roles; scope = Team or Own, never All, for non-staff)
- [ ] `Support Triager`: read/edit Cases of own teams, can assign to users in own teams.
- [ ] `Internal Staff`: broad Team-level access to Cases, Tasks, Responses, Contacts, Accounts.
- [ ] `Roster Expert`: read Tasks and Responses of own team, edit own Tasks, create comments. No access to Contacts or Accounts.
- [ ] `Volunteer`: the same as Roster Expert but more restricted (e.g. no Cases).
- [ ] `Kobo Integration` (API user role): create Case, Task, Contact, Account; read Account/Team lookups needed; **nothing else**.

**Entities and fields** (Entity Manager; implement as git-tracked metadata where practical)
- [ ] Custom entity `Response`: name, status (Planning, Active, Closed), emergency type, country, start/end dates, lead (user), team (link). Add tab and list/detail layouts.
- [ ] Task: add `response` (link to Response), enum `status` with the board columns (e.g. Backlog, To do, In progress, Blocked, Done), enable **Kanban**, enable **Collaborators**. Save a list filter per response for the board.
- [ ] Case: add `source` (enum: Kobo form, Email, Manual), `koboSubmissionUuid` (varchar, **unique**), `koboFormId`, `requestingOrganisation` (link to Account), `category`, `priority`.
- [ ] Contacts/Accounts: use Accounts for partner orgs, Contacts for people at those orgs. Add Contact field `profileType` (Roster, Volunteer, Partner contact) and `availability` (text) for Workflow B sign-ups.
- [ ] Constrain Case to one team (see Phase 5).

**Seed data** (script, idempotent)
- [ ] Create users: 1 triager, 2 internal, 2 roster, 2 volunteers; spread across the test teams so that **at least one user is in Response 1 only, one in Response 2 only, and one in both**.
- [ ] Create 3 partner Accounts with Contacts for the consortium tests.

## 7. Phase 3: Integration identity

- [ ] Create an Espo **API user** assigned the `Kobo Integration` role, with API-key auth. Record the key only in the environment, not in the repo.
- [ ] Verify with a curl script that the key can create a Case and **cannot** read unrelated records or list users.
- [ ] Decide which team new Kobo-created Cases land in (see mapping in Phase 4). The API user may need to be allowed to set teams; check and document.

## 8. Phase 4: Kobo to Espo connection

**4.1 Build the Kobo forms (staging)**
- [ ] `support-request.xlsx`: requester name, email, organisation, project/consortium (select_one), category, priority, description, optional attachment. Use the `xlsform-expert` skill if available.
- [ ] `volunteer-availability.xlsx`: name, email, skills, languages, availability, deployment preferences.
- [ ] Deploy to Kobo **staging** via the MCP tools; keep project IDs in `REPORT.md`.

**4.2 Choose the delivery path.** Check what Kobo's REST services support on the staging server (custom headers, payload format, any field/payload customisation) and record it.
- Path 1 (preferred if Kobo can send the needed headers and shape): Kobo REST service posts straight to Espo `/api/v1/Case` with `X-Api-Key`. Kobo's payload will not match Espo's field names, so this works only if Kobo allows payload shaping.
- Path 2: Kobo REST service posts to a **mapping proxy** (reuse Josh's KoboHooks if suitable), which translates the submission into Espo's schema and calls the Espo API. The mapping lives in `kobo/mapping/`.
- Record the path chosen and why.

**4.3 Mapping and behaviour requirements** (whichever path)
- [ ] Map Kobo submission fields to Case/Contact/Account/Task fields per `kobo/mapping/*.yaml`.
- [ ] Look up or create the requesting Contact by email; link to Account by organisation name; do not create duplicates.
- [ ] Set the Case team from the project/consortium answer.
- [ ] **Idempotency:** store Kobo `_uuid` in `koboSubmissionUuid`. A retried or duplicate delivery must not create a second Case.
- [ ] **Failure handling:** if Espo is down or returns 4xx/5xx, the failure must be visible (`get_hook_logs`) and retryable (`retry_hook`) without data loss.
- [ ] Attachments: decide whether to link back to the Kobo attachment URL or upload to Espo. Linking is acceptable for the test; note the access implications of Kobo URLs.
- [ ] Workflow B: a volunteer-availability submission creates a Contact with `profileType` and `availability`. Activating someone as a user stays a **manual or workflow step**, not automatic.

## 9. Phase 5: Automation (depends on Advanced Pack)

If Advanced Pack is available, use Workflows; otherwise use core Formula scripts in Entity Manager and record anything that cannot be done.
- [ ] On new Case from Kobo: notify the team's triager(s) (email and in-app notification).
- [ ] Triage: when the triager sets the assignee, notify the assignee; keep the Case in exactly one team.
- [ ] Escalation: if a Case is unassigned for N hours, notify the team lead (use a short interval in tests).
- [ ] On creating a Response: create a standard set of starter Tasks (e.g. set up Kobo project, confirm roster, comms plan) linked to the Response and its team.
- [ ] Assignment notifications for Tasks.
- [ ] Record in `REPORT.md` which automations were possible with core Espo only.

## 10. Phase 6: Auth (optional, only after Phases 1-5 pass)

- [ ] Stand up a test OIDC provider (authentik or Auth0) and configure Espo OIDC login with **fallback login enabled for admins**.
- [ ] Note that Espo's built-in 2FA likely will not work with OIDC; MFA would live in the identity provider.
- [ ] Test first-login user creation and confirm a new user has **no access** until added to a team.
- [ ] Regular users can use only one authentication provider; document the bridge approach for Google/Microsoft logins.

## 11. Test plan

Write each test as a script in `tests/cases/`, with expected result and actual result in `REPORT.md`.

**Connection (Workflow A)**
- [ ] T1: Submit the support form on Kobo staging -> Case appears in Espo with correct fields, team, requester Contact and Account. Latency recorded.
- [ ] T2: Redeliver the same submission (`retry_hook`) -> still exactly one Case.
- [ ] T3: Stop Espo, submit, restart, retry -> Case created, failure was visible in the hook logs.
- [ ] T4: Malformed or missing required fields -> clear error, no partial records.
- [ ] T5: Triager is notified; triager assigns to another user; assignee is notified.
- [ ] T6: Submission for Consortium A and one for Consortium B land in their own teams.
- [ ] T7: Volunteer-availability submission creates a Contact with `profileType`.

**Isolation (the key risk)**
- [ ] T8: User in Response 1 only cannot see Response 2, its Tasks, or Cases of Consortium A/B (UI list views, global search, direct URL, and API).
- [ ] T9: User in both responses sees the union and nothing more.
- [ ] T10: Volunteer cannot assign tasks to users outside their team, cannot see the user list beyond their team, and cannot edit others' tasks.
- [ ] T11: Consortium A staff cannot see Consortium B Cases or partner Accounts.
- [ ] T12: The API key cannot read data outside its role.
- [ ] T13: Removing a user from a team revokes access to that team's records immediately.

**Workflow B**
- [ ] T14: Create Response -> starter Tasks appear; the Kanban board filtered by that Response shows them in the right columns.
- [ ] T15: Drag a Task between columns as a Roster user (allowed) and as a Volunteer on someone else's task (denied).
- [ ] T16: Closing a Response and removing members leaves its records readable only by staff.

## 12. Deliverables

- [ ] Git repo as laid out in section 4, reproducible from a clean checkout with one documented command sequence.
- [ ] `REPORT.md`: versions, decisions, delivery path chosen, test results (pass/fail with evidence), automation limits, and any deviations from this plan.
- [ ] `docs/manual-steps.md`: every step that could not be scripted.
- [ ] A short **go/no-go recommendation** for single-instance use, based on T8-T13, with the remaining risks listed.
- [ ] A list of open questions for Josh.

## 13. Out of scope

- Production rollout, data migration, DNS/TLS hardening beyond what testing needs.
- Replacing Kobo's own email notification features.
- Building a polished volunteer-facing UI beyond what Espo provides with a restrictive role.

## 14. Known risks to keep an eye on

- Admin settings, custom fields and automations are global to the instance; workflows are admin-only.
- A role misconfiguration can expose one project's data to another. T8-T13 exist to catch this.
- Extension licences may not cover multiple instances if we later fall back to instance-per-project. Check with Espo before assuming.
- Browser sessions: two Espo instances on the same domain log each other out; use subdomains if that situation arises.

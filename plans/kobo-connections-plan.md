# Connecting a Kobo form to EspoCRM in one conversation

Status: 2026-11-06. Phases 0–3 done, phase 4 built and tested (the EspoCRM MCP, kobo-espo-bridge
`espo_mcp/`, live on the test droplet at /bridge/mcp); its acceptance run in Claude Code is
next. See REPORT.md, "Kobo connections and one bridge service".

## Goal

Someone who runs an EspoCRM instance with the bridge says to an agent: *"I want a grant
application form in Kobo, and each application should become a record in EspoCRM for the
Grants team, with Amina notified."* The agent builds or picks the form, shows what each
application will become, sets it up, makes a test submission and shows the record that
arrived. Nobody edits a file, opens ssh, copies a key or restarts a container.

Today the same thing takes nine steps across two repositories (a TOML template, a compose
service, four lines of `deploy/bridges.sh`, sharing on Kobo, a deploy). Most of those steps
are plumbing, not choices. The real choices are only three:

1. which Kobo form;
2. what it becomes in EspoCRM (a contact, a case, a new kind of record);
3. which team owns the records, and who's told.

Everything else should have a default or be done by the software.

## What already exists

**kobo-mcp** ([kobotoolbox/kobo-mcp](https://github.com/kobotoolbox/kobo-mcp), hosted at
`https://mcp.kobolabs.dev/mcp`) already covers the whole Kobo side, acting as the signed-in
Kobo user. We use it as it is:

| Step | kobo-mcp tools |
|---|---|
| Build or change the form, try it before deploying | `preview_form`, `deploy_form`, `convert_xlsform`, `get_form_content` |
| Find an existing form | `list_projects`, `get_project` |
| Its questions: xpaths, types, choices | `describe_form` |
| Let the bridge's Kobo account read it (and, for lists, edit it) | `share_project` |
| A test submission, real or dummy | `create_submissions` |
| Lists on the form (the bridge does this itself afterwards) | `list_form_media` |

Patterns worth copying from it:
- **No secrets in the chat.** kobo-dash's view-only token is typed into kobo-dash's admin
  page, never into the chat. Here, the EspoCRM admin password and the bridge's Kobo token
  stay on the server.
- **Nothing destructive on the first call** (`tools/confirm.py`): the first call shows what
  would happen and returns a token tied to that exact target, and only a second call that
  carries the token acts.
- **Task-shaped tools**, not raw API access, and a guide prompt (its "Email alerts" prompt)
  that walks the agent through a task.
- `mcp>=2.2,<3` (`MCPServer`), Streamable HTTP plus stdio, header mode for Claude Code, and
  OAuth for claude.ai.

**kobo-espo-bridge** already does the work once a template exists: `setup.py` makes the
fields, layouts, teams, role and API user, and `bridge.py` polls, routes, notifies, retries,
and redoes setup when the form changes. **kobo-espo's agents** already keep their setup as
EspoCRM records (Agent, Agent route), read by one runner, with `agents/sync.py` making each
agent's API user. Connections should work the same way.

## Design

### 1. A connection is an EspoCRM record

A new entity, **Kobo connection** (`CKoboConnection`), made by the bridge itself (not by
kobo-espo's seed), so that every instance using the bridge has it:

| Field | What it is |
|---|---|
| name | "Grant applications" |
| active | on/off. Off pauses the polling and keeps the ledger. |
| koboForm | The form's name or uid, as `[form] name` is now |
| template | The template as TOML: the same format as `kobo/templates/*.toml`, the README's reference unchanged |
| entity, team, notify | Read-only summary of the template, for people reading the record |
| status, lastPass, created, waiting, lastError | Written by the bridge each pass: what `status.json` holds now |

The template text is still the single source of truth, so there's one format to document
and test. Template files on disk keep working: kobo-in-a-box, the tests, and kobo-espo's
four forms until they're moved. A file template is a connection that can't be edited in
EspoCRM.

### 2. One bridge service for all connections

`bridge.py serve` replaces "one container per template":

- Each pass it reads the active connections (and any file templates). For each one, it
  works in its own state directory (`/state/<connection id>`), with its own ledger and
  cursor, as one `bridge.py run` does now.
- **New or changed connection → setup first.** `setup.py`'s `main()` becomes a function
  that `serve` calls when a template's hash or its form changes. This already happens per
  template with `--if-form-changed`. The API keys it makes go to the service's own secrets
  file. A connection whose setup fails shows the reason in `lastError` and is skipped until
  it changes.
- Records are still written with **each connection's own API user**, so least privilege
  holds where the data is handled. The service also holds the admin password, for setup.
  That's what `deploy/bridges.sh` uses now, and it moves from the operator's laptop to the
  server.
- Connections run one after another in one process. "One bridge per template" still holds
  (no two pollers on one form), because there's only one process.
- Status goes into the connection record, so admins see it in EspoCRM.
  `deploy/bridges.sh logs` and `bridge.py failed` stay for debugging.

After this step, kobo-espo's compose has one `bridge` service instead of four, and
`deploy/bridges.sh` has no list of bridges to keep up to date.

### 3. A default mapping from the form

`propose(form_content, entity)` in the bridge turns a deployed form into a template. Each
question becomes a field with its label, and with a type taken from the question's type:

| Kobo | EspoCRM |
|---|---|
| text | varchar (text if multiline) |
| integer / decimal | int / float |
| date / dateTime, start / end | date / datetime (UTC, as now) |
| select_one / select_multiple | enum / multiEnum, options from the form's choices |
| image, audio, file | attachment (`copy_media`) |
| geopoint | varchar "lat lon" |
| note, calculate, hidden fields | left out (listed) |
| repeat groups | left out with a warning (not supported, as in REPORT.md) |

On Contact, questions named like `name`, `email` and `phone` map to the built-in fields,
and `match` defaults to the email. Field names are `c` + the question's name in camelCase.
An existing field of the same type is reused, and a clash of types gets a suffix. The
proposal comes with a list of what was left out and why, so the agent can tell the user.

The test of this step: run it on kobo-espo's four forms, and the result should be close to
their hand-written templates. Every difference is either a default to fix or a deliberate
override.

`preview(template, submission)` runs one submission through `to_record` without writing
anything. It shows the record that would be made, the team, and who would be told.

*Done 2026-11-06* (`propose.py`). Against kobo-espo's forms the proposal matches the
hand-written templates but for three naming choices (`registeredAt`, `installedAt`, the
case's name), after four defaults were fixed: short labels from the question's name, not
its text; a Case's requester questions as `[requester]`, and `priority` as the case's own
when the choices are EspoCRM's; only the name, match and requester's email required (a
form's other required answers can be missing from older versions); a `..._code` question
as `match` on custom entities. With the fields EspoCRM has, links and attachment fields
are reused; a link from a list file gets a warning to check (ids or codes). site-visit,
a follow-up form, has no default. `float` is new in the bridge (decimal questions).
Tests: bridge unit tests 66 (13 new); kobo-espo `tests/test_propose.py`; serve.py K5, a
proposed template for a form with every question type set up and run on the droplet,
and the record exactly as `preview` said.

### 4. The EspoCRM MCP (in kobo-espo-bridge, `mcp/`)

Served by the same service, behind the instance's Caddy at `https://<espo host>/bridge/mcp`.
Only EspoCRM **admins** can connect. The tools are task-shaped: there's no generic record
read or write.

| Tool | What it does |
|---|---|
| `bridge_info` | The instance, the bridge's Kobo server and account (who to share forms with), connections and their status |
| `list_teams`, `list_users`, `list_entities` | What records can go to and who can be told |
| `propose_connection` | Form uid + entity + team + notify → a template, what was left out, and a preview of the form's latest submission. Writes nothing. |
| `create_connection` / `update_connection` | Saves it, after a first call that shows the change (the confirm-token pattern). The next pass does setup. |
| `create_entity` | A new kind of record ("Application"), with confirmation. Made through the Entity Manager API, as seed.py does |
| `grant_access` | Which roles may see the new entity's records, at "team" level only (never "all") |
| `test_connection` | Runs a pass for this connection now, and reports the record made from the newest submission (a link) or why it's waiting |
| `connection_status` | Last pass, counts, waiting submissions and the oldest one's reason |
| `pause_connection` | Off, with confirmation. There's no delete: the ledger and records stay |

Before anything else, `propose_connection` checks that the bridge's Kobo account can see
the form. If it can't, the error says exactly what to ask kobo-mcp for: *"share project
aXy… with `bridge_acct`: View submissions"* (plus Edit form if the connection puts a list
on the form).

A prompt, **Connect a Kobo form to EspoCRM**, gives the agent the order of steps across
both servers:

1. `bridge_info` (EspoCRM MCP) → which Kobo server and account.
2. Build or find the form: `preview_form` / `deploy_form`, or `list_projects` (kobo-mcp).
3. Ask the three questions. If needed, `create_entity`.
4. `share_project` with the bridge's account (kobo-mcp).
5. `propose_connection`, show the mapping and the preview, take the user's changes, then
   `create_connection`.
6. `create_submissions` with a dummy test entry (kobo-mcp), then `test_connection`, and
   show the record.
7. `grant_access` for the people who'll work on the records, and say what's left by hand
   (users and their teams).

**Auth.** First, header mode: an MCP key per admin, made on the server
(`bridge.py mcp-key <espo admin user>`) and given to `claude mcp add --header`. Kept as a
hash. That's enough for Claude Code. Then OAuth for claude.ai and Claude Desktop: a
sign-in page that checks an EspoCRM admin's username and password (and 2FA code) against
EspoCRM's `/App/user` and seals the session, as kobo-mcp seals Kobo tokens. The password is
never stored.

### What doesn't change

kobo-mcp (none of its code). The template format. The bridge's polling, ledger and
retries. kobo-in-a-box, which keeps running `bridge.py run` per template until its own
switch (the 2026-11-05 decision: a separate change, after its 60-check e2e).

## Phases

Each phase can be used on its own. Phase 2 already removes the plumbing.

0. **Checks.** Making an entity and its fields through the API on EspoCRM 10.0.11 as an
   API-only admin (seed.py does it with Basic auth). Whether an API user can be
   admin-free and still run setup (probably not: keep the admin password). Which MCP SDK
   version kobo-mcp pins now.
   *Done 2026-11-06, on the test droplet:*
   - An entity (`createEntity`), its varchar and text fields, a record with a TOML
     template in the text field read back unchanged, and `removeEntity`: all fine as
     admin with Basic auth.
   - An API user can't run setup. Even with a role allowing all it may, the field
     manager, layouts, Settings, Role, User and Entity Manager calls all return 403. A
     role can't grant edit on users at all ("Level `all` is not allowed"). An API user
     changed to type admin loses its key (401 on every call). So setup needs an admin's
     password: keep it on the server, as the risks below recommend.
   - kobo-mcp pins `mcp>=2.2,<3` (Python ≥3.12), as in its latest commit (2026-11-03).
1. **Setup as a function.** `setup.py`'s `main()` → `setup(template, espo, kobo, secrets,
   state_dir)`. CLI unchanged. Unit tests unchanged (53).
2. **Connections + `serve`.** The entity, the reading of connections and files, per-
   connection state, status written back. kobo-espo's compose goes to one bridge service.
   Acceptance: connection tests 73/73 (fake Kobo) and 72/72 (real) through `serve`; a new
   connection made in the EspoCRM UI (template pasted in) starts polling within one pass,
   with no other change.
3. **`propose` and `preview`.** Unit tests on the four kobo-espo forms and a form with
   every question type.
4. **The MCP, header mode.** The tools, the confirm gate, the prompt. Tests with fake Kobo
   (each tool, the confirm tokens, a non-admin refused). Acceptance, on the test droplet
   and the Kobo test account: in Claude Code with kobo-mcp and this MCP, from *"I want a
   grant application form"* to a record in EspoCRM in under 10 minutes, with no file
   edited and no ssh.
   *Built 2026-11-06:* `espo_mcp/` (tools.py, confirm.py, keys.py, server.py), a separate
   `bridge-mcp` service (the bridge stays stdlib only; the MCP SDK is in its image), not
   in `serve` itself: test_connection waits for the service's pass instead of running one.
   Named espo_mcp, not mcp (it would shadow the SDK). Added: `preview_template`,
   `resume_connection`. Tests: kobo-espo `tests/cases/mcp.py` 21/21, `mcp_http.py` 8/8.
5. **OAuth sign-in** with an EspoCRM admin account. Acceptance: the same task in claude.ai.
6. **Manual.** A "Connect a form" page (the steps and an example conversation), replacing
   the template section of "Running it". The bridge's README: `serve`, connections, the MCP.
7. **Move kobo-espo's four templates** into connection records, keeping the files as the
   tests' fixtures.
   *Done 2026-11-06:* `bridge.py serve adopt FILE...` (the record kept, its state moved to
   the record's; a file without a connection gets a new record; again, nothing), run by
   `deploy/bridges.sh` on every `up`; the bridge service no longer mounts the files. On
   the droplet, nothing was rescanned. serve.py K6.

## Risks and open questions

- **The admin password on the server**, held by a long-running service, where today
  only `deploy/bridges.sh` uses it. Alternatives: setup only when the MCP is called (but
  then connections edited in the EspoCRM UI wait for someone), or a second process for
  setup. Recommendation: accept it. The password is already on the server
  (`/root/kobo-espo.secrets`).
- **seed.py puts roles back as it defines them.** Access granted with `grant_access` would
  be undone at the next seed. The seed has to keep the permissions for entities it doesn't
  define. (Phase 4, before `grant_access`.)
- **Mapping quality** decides whether this feels simple. The default should be good enough
  that most users change nothing. Phase 3's test on real forms is the check.
- **Who connects.** Admins only, because the MCP changes fields and roles for the whole
  instance. If partners' staff should set up their own forms, that needs a narrower role
  (connections for their team only, no new entities). Not in this plan.
- **Several bridges' Kobo accounts or servers per instance** (Global and EU): one for now,
  in `bridge_info`.
- **Lists to forms** (`[[list]]`) and follow-ups (`[followup]`) have no defaults. The agent
  can write them into the template, and `propose_connection` validates them. A
  task-shaped `add_list` tool later, if they turn out to be common.

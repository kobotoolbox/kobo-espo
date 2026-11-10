# Workflow packs: workflows as data on a standard instance

Status: 2026-11-10, a plan, not started. To start once the CSO mapping's tests
(`tests/cases/cso.py`) pass on staging, before its Phase 5.

## Goal

The support desk, rosters, site monitoring, grants, cluster projects, the 5W and the CSO
mapping should be **workflows built on one standard infrastructure** (the bridge, the
agent runner, the formulas' building blocks, the dashboard feeds), each set up by data,
not by editing shared code. A new workflow, or a project's variant of one, is a new
folder. Turning a workflow on in an instance is normal per-project setup: which packs, for
which teams and countries, and their people.

## Where we are

The engine is already standard. The CSO mapping (Workflow F) needed **no change to
kobo-espo-bridge**: forms, repeats, lookups, geopoints, lists and the match on a code
were all there. Its new shared pieces (the `geocode` tool, `espo/seed/admin_areas.py`,
level `admin0`) are reusable by any workflow.

The workflows are not packaged. Each lives in edits to shared code:

- `espo/seed/seed.py` (1,145 lines) holds every workflow's entities, fields, links,
  codes, roles, teams, test users, layouts, reference data and data migrations, in
  Python. Workflow F added about 190 lines to it, among them the line unpacking `TEAMS`
  into names.
- A shared entity takes logic from each workflow that uses it: `CFocalPoint`'s formula
  has the 5W's block and the CSO mapping's.
- The agents' "Works on" (`CAgent.entity`) lists every entity agents may work on, so a
  workflow with agents edits the Agent entity.
- The agents' Tools field listed the code tools by name (a new tool failed the seed: the
  CSO mapping's `geocode`); since 2026-11-10 it's made from `agents/tools.py`.
- Formula patterns are written again in each workflow:

  | Pattern | Written in |
  |---|---|
  | teams follow the parent record | activity locations, focal points, sites, tasks, responders, CSO places, updates, focal points |
  | short codes | one snippet already (`_code.formula`), the model for the rest |
  | P-codes up an area's parents | CSO places, CSO updates (twice in one workflow) |
  | the latest one counts | CSO updates (superseded), a profile's rows from the submission before |
  | fields copied onto rows for the feeds | CSO places, CSO updates |
  | data checks as flags | activities, activity locations, CSO updates |

- Single-connection provisioning exists in kobo-espo-bridge: `setup.py` makes a
  template's fields and its bridge user, and the EspoCRM MCP has `create_entity` and
  `grant_access`. kobo-in-a-box's template has `[[role]]`, `[[api_user]]` and `[demo]`.
  These are pieces of the same idea, one connection at a time.

## Design

### 1. A pack is a folder

```
workflows/
  core/          agents, the task board, email, settings, admin areas, organisations
  support/       Workflow A: cases from the support form
  roster/        Workflow B: volunteers and roster experts
  sites/         Workflow C: sites, visits, standards
  grants/        Workflow D: applications, due diligence
  responses/     responses and cluster projects
  fivew/         Workflow E: the 5W
  cso/           Workflow F: the CSO mapping
    workflow.toml   entities, fields, links, codes, teams, roles, layouts, data, users
    lists/          choice lists with codes (cso-lists.json), read by enums and forms
    forms/          the forms, or their generator (cso.py), and the bridge templates
    formulas/       <Entity>.<script>.formula: this pack's block for that entity
    agents.json     its example agents
    data/           reference data (admin areas are core's; a pack's own lists)
    tests/          its test cases (today's tests/cases/cso.py)
```

`workflow.toml`, as TOML like the bridge templates (stdlib `tomllib`, no dependency):

- `requires`: the packs it builds on (`fivew` requires `responses` and `core`);
- `[entities.<Name>]`: label, plural, icon, stream, status field, and its fields. An enum
  names a list instead of spelling its options (`enum = "cso_types"`, `many = true`), so
  `cso_enum()`, `enum()` and `choices()` go;
- `[fields.<Entity>]`: fields on an entity defined elsewhere (EspoCRM's `Case`, `Task`, or
  another pack's, as the CSO mapping's `current` on `CFocalPoint`);
- `links`, `codes` (entity and prefix), `teams`, `layouts` (detail fields, list columns,
  relationship panels, board, filters);
- `[roles.<Name>]`: access per entity. A role named in two packs is the union of their
  access, so a pack adds its entities to `Internal Staff` without editing core;
- `agent_entities`: the entities its agents may work on (the Agent's "Works on" is made
  from every pack's);
- `[[data]]`: reference data to load (a file, its entity, the field it matches on, and
  whether records no longer in the file are removed, as admin areas are);
- `[[users]]`: test users, made only with `--users`;
- `removed`: fields and links it no longer has (today's `OBSOLETE_FIELDS`, `OBSOLETE_LINKS`).

### 2. The loader

One generic `apply` (see the questions for where it lives) that reads the packs an
instance has, in `requires` order, and makes EspoCRM so: what `seed.py`'s functions do
today (`ensure_entities`, `ensure_field`, links, layouts, roles, teams, formulas, codes'
backfill, agents, reference data), driven by the packs' data. Idempotent, as the seed is.
It never deletes records, and removes fields only when a pack lists them in `removed`.

A pack that needs something the data can't say (a one-off migration, as `OLD_CLUSTERS`
moving old sector codes) has a `migrate.py` with a `migrate(espo)` the loader runs after
applying. An escape hatch, kept small: what several packs need goes into the loader.

`espo/seed/seed.py` becomes a few lines: apply the packs of this instance.

### 3. Formula blocks (traits)

The patterns above become **shared snippets with parameters**, as `_code.formula` is
today, switched on per entity in `workflow.toml`:

```toml
[entities.Presence.traits]
teams_from = "cso"                        # its teams are its CSO's
pcodes_from = "adminArea"                 # pcode1..3, country, from the area's parents
copy_from = { link = "cso", fields = ["csoType", "settings", "populations", "roles", "listed"] }

[entities.CsoUpdate.traits]
supersede = { by = ["cso", "adminArea"], when = "keyCheck in ok, confirmed" }
```

The loader writes an entity's script from: the traits' snippets, then each pack's own
block for that entity (`formulas/`), in `requires` order, each fenced with its pack's
name. A pack's own formula is what is particular to it (the CSO key, consent); the
patterns are shared and tested once.

### 4. An instance says which packs, for whom

`instance.toml` (one per instance, in `deploy/` or the instance's secrets directory):

```toml
packs = ["core", "cso"]                 # a WHO instance: the CSO mapping only
[cso]
countries = ["KEN"]                     # makes CSO: Kenya, loads Kenya's admin areas
```

Pack parameters (`[cso] countries`) are how a project's setup differs: data, not code. The
staging droplet has every pack. The MCP (kobo-espo-bridge's EspoCRM MCP) gets
`list_workflows` and `apply_workflow`, so the agent-guided setup of the connections plan
can turn a pack on, with the usual confirm step.

### 5. The forms and the bridge templates

A pack's forms and templates live in the pack; the bridge reads templates as today.
Template files don't reach a running instance's connection records by themselves (they
are `CKoboConnection` records, the template's text in them): `apply` reports a pack's
templates that differ from the instance's connection records, and `--update-connections`
writes them, never silently.

## Checking it changed nothing

Moving the workflows into packs is meant to change nothing in EspoCRM. So, first:

- `tools/snapshot.py` dumps what the seed makes, in a stable order: every custom entity's
  metadata (fields, links, client defs), the layouts of those entities, the roles, teams,
  formulas, agents and routes, the number of reference records per entity and country.
- Taken on staging before the refactor; after each pack moves, the snapshot again: **the
  diff is empty**, or each difference is explained (e.g. a formula's text reordered into
  traits, the same behaviour, its tests green).
- Every test suite, as `tests/run_all.sh` runs them: connection, isolation, fivew,
  projects, agents, mcp, mcp_people, dash_feeds, look, cso.

## Phases

0. **Snapshot**: `tools/snapshot.py`, taken on staging (after the CSO tests pass).
1. **The loader and `core`**: `apply` with entities, fields, links, codes, layouts, roles
   (merged), teams, formulas (each pack's blocks, fenced), agents, reference data,
   `removed`, `migrate.py`; `core` as the first pack; `seed.py` calling it. Snapshot diff
   empty.
2. **The workflows, one at a time**, smallest first: support, roster, sites, grants,
   responses, fivew, cso. After each: its tests green, snapshot diff empty. The tests move
   into their packs; `tests/run_all.sh` runs each pack's.
3. **Traits**: teams from a parent, P-codes from an area, copy from a parent, supersede,
   current rows of the latest submission, data checks; the formulas rewritten on them,
   each pack's tests green. The diff here is formula text only.
4. **Instances**: `instance.toml`, pack parameters (`cso.countries`), the droplet's file
   (every pack); a second, small instance with `core` and `cso` only, on a local EspoCRM
   (`docker-compose.yml`), to show a pack stands alone.
5. **The MCP and the manual**: `list_workflows`, `apply_workflow` (confirm first), the
   templates check; a manual page "Workflows" (what a pack is, turning one on, making one).
6. **kobo-in-a-box**, later and separately: its template's `[[role]]`, `[[api_user]]` and
   `[demo]` as a pack, when it switches to kobo-espo-bridge.

## Questions

- **Where the loader lives.** In kobo-espo-bridge (the shared repo: kobo-in-a-box and any
  other instance would use it, and the MCP's `apply_workflow` calls it in place) or in
  kobo-espo (where the packs are). I suggest kobo-espo-bridge (`workflows.py`), the packs
  in kobo-espo, and a pack directory the loader is given, so packs can live anywhere.
- **TOML or JSON for `workflow.toml`.** TOML matches the templates and reads well for
  people; entities with fifty fields are long in it either way. JSON is what the lists
  and agents use now. I suggest TOML for `workflow.toml`, lists and agents staying JSON.
- **Shared entities** (`CFocalPoint`, `CAdminArea`, `COrganisation`): in `core` or in the
  first pack that needed them. I suggest `core` for admin areas and organisations (every
  humanitarian workflow wants them), and focal points in `core` too, each pack adding its
  link and block.
- **Turning a pack off.** Not in this plan: `apply` only adds. Removing a pack's entities
  from an instance is a manual, deliberate step (data would go with them).

## Risks

- **EspoCRM's metadata calls are slow** (every field PUT clears the cache; the seed takes
  over 10 minutes on staging) and sometimes fail with "Error while clearing cache" while
  EspoCRM's own jobs rebuild it. The loader should write only what differs (compare with
  the metadata first, as the reference data already does) and retry that error once.
  That alone would make a rerun take a minute, not ten.
- **The snapshot diff is only as good as what it dumps**: check it catches a deliberate
  change (a field's label, a role's access) before trusting an empty diff.
- **Formula order on shared entities**: blocks from two packs on one entity run in
  `requires` order; a block must not depend on another pack's having run, or say so in
  `requires`.

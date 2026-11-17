# kobo-espo

EspoCRM as request intake and response tasking hub, connected to KoboToolbox: a test of
[the plan](plans/espo-kobo-setup-plan.md) on one throwaway EspoCRM. Results and the
recommendation are in [REPORT.md](REPORT.md); the user manual, with screenshots, is
`site/` (GitHub Pages).

The Kobo ↔ EspoCRM connection is [kobo-espo-bridge](../kobo-espo-bridge), shared with kobo-in-a-box;
this repository has the instance's setup, its forms and templates, and the tests.

```
docker-compose.yml          EspoCRM 10.0.11 (apache), MariaDB 11.4, its scheduler, Caddy (TLS), the bridge
deploy/up.sh                the stack onto the droplet (ESPO_SSH), secrets generated there
deploy/Caddyfile            TLS for ESPO_HOST: EspoCRM, and the bridge's EspoCRM MCP at /bridge/mcp
deploy/bridges.sh           the bridge service, kobo-espo-bridge's `serve`: every connection, set up on the server (up | down | logs)
workflows/<pack>/           the workflows as packs: workflow.toml (entities, fields, roles, teams, layouts,
                            data), lists, formulas, agents (plans/workflow-packs-plan.md)
espo/workflows.py           loads and applies the packs; espo/seed/seed.py applies deploy/instance.toml's
espo/formula/               the formulas' shared snippets (_code, _agent-guard)
espo/look/                  Kobo's look: a module (metadata) and kobo.css, logo, favicon (plans/espo-kobo-look-plan.md)
kobo/forms/                 the Kobo forms as XLSForm rows (.json; .xlsx from export.py)
kobo/templates/             the four forms' bridge templates: the tests' fixtures, and the first copy of
                            each connection on a new droplet (then edited in EspoCRM)
tests/                      run_all.sh, cases/ (look, isolation, workflow_b, agents, serve, connection, latency),
                            test_propose.py, results/
site/                       the manual: pages/, build.py, shots.py, demo-data.py
agents/                     agents set up in EspoCRM (plans/espo-agents-plan.md): runner.py, llm.py,
                            tools.py, sync.py, setup/ (the example agents), models.toml
deploy/agents.sh            sync (an API user and role per agent), then the agent runner (up | sync | down | logs)
docs/manual-steps.md        what isn't scripted
```

## From a clean checkout

```bash
cp .env.example .env        # ESPO_HOST, ESPO_SSH; KOBO_URL, KOBO_TOKEN of a throwaway Kobo account
                            # (on kf/eu.kobotoolbox.org also KOBO_TEST_ACCOUNT_ON_PRODUCTION=yes)
git clone <kobo-espo-bridge> ../kobo-espo-bridge
deploy/up.sh                # needs a host with Docker and ESPO_HOST's DNS pointing at it
tests/fetch-secrets.sh
                            # outgoing email: a Resend send-only API key in secrets/resend.key
python3 -I espo/seed/seed.py --users
deploy/bridges.sh
deploy/agents.sh            # ANTHROPIC_API_KEY in .env for agents with a model (or Bedrock, below)
tests/run_all.sh            # or: tests/run_all.sh --kobo real
```

**Kobo connections.** One bridge service runs every form's connection, each a record in
EspoCRM (Kobo connections) with its template in it. kobo-espo's four were made from
`kobo/templates/` (`serve adopt`, in `deploy/bridges.sh`) and are edited in EspoCRM now,
like any connection an admin makes. It sets each one up when its template changes, and shows its status
in its record. An admin can also connect a form from a conversation, with the bridge's
EspoCRM MCP (`https://ESPO_HOST/bridge/mcp`, a key per admin) next to kobo-mcp. See the
manual's [Connecting a form](site/pages/connect.html) and
[Running it](site/pages/running.html#checking), and kobo-espo-bridge's README
(`serve`, `propose`, `espo_mcp`).

Python 3.11+ (stdlib only, but the `anthropic` SDK for the agent runner, `openpyxl`, Pillow and Playwright for the forms' .xlsx,
the demo photos and the screenshots). Secrets never go into git: `.env*` and `secrets/` are
ignored; the droplet keeps its own in `/root/kobo-espo*.secrets` (mode 600).

Agents with a real model, from your own machine through Amazon Bedrock (your AWS login, no
Anthropic key; Sonnet 5.5 for test runs): the manual's "Running it" → "Agents".

## Licence

GNU Affero General Public License v3.0: see [LICENSE](LICENSE).

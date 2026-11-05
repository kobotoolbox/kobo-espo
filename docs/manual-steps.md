# Manual steps

Everything else is scripted (`deploy/up.sh`, `espo/seed/seed.py`, kobo-bridge's `setup.py`
through `deploy/bridges.sh`, the tests). These are the steps that stay manual, by design
or because EspoCRM only has them in its UI.

## Per person

**A saved board filter per response.** EspoCRM's saved filters belong to the user who
saves them; there's no API to give everyone a shared one without a custom PHP filter
class. Each person, once per response they work on:

1. Tasks → switch to the **Kanban** view (top right).
2. Search panel → add the filter **Response** → pick the response.
3. The filter menu (funnel) → **Save filter** → name it after the response.

Opening the response itself shows its tasks too (the **Tasks** panel), without a filter.

**Making a volunteer a user** (plan §8.3: deliberately not automatic). When someone from
the roster is deployed:

1. Administration → Users → Create: user name, their email, **Role** Volunteer (or Roster
   Expert), **Teams** the response's team only. Password: let EspoCRM email them a link
   (needs SMTP) or set one and send it separately.
2. Assign them tasks on the response's board.

When they leave: remove them from the team, and reassign their open tasks (a user taken
out of a team still sees the tasks assigned to them; see REPORT.md, T13).

## Per Kobo form

The bridge's Kobo account must see each form. On the test account that's automatic (it
owns them). With a separate bridge account (recommended), share each form with it:

- intake, volunteer and registration forms: **View submissions**;
- forms that get a list (`responses.csv`, `standards.csv`, `sites.csv`): **Edit form** too,
  so the bridge can replace the file and redeploy.

A new response's site visit form needs its own `[[list]]` entry (its team) and
`[followup]` form name in a template: copy `kobo/templates/site-visit.toml`.

## Once, for a real instance

- **SMTP** (Administration → Outbound Emails) if notifications should also go by email;
  then Administration → Notifications → "Email notifications upon assignment" and
  "...mentions in posts". Not set up on the test droplet (in-app notifications only).
- **Admin password**: the one `deploy/up.sh` generated is in
  `/root/kobo-espo.secrets` on the droplet. Change it, and turn on 2FA for admins
  (Administration → Authentication).
- **Unique submission uuid** (optional): EspoCRM's field manager can't make a varchar
  unique. A unique index on `cKoboSubmissionUuid` needs a custom metadata file
  (`custom/Espo/Custom/Resources/metadata/entityDefs/Case.json`, `indexes`) and a rebuild.
  Not needed while there's one bridge per template (see REPORT.md).

## Teardown of the test droplet

```bash
doctl compute droplet delete espo-kobo-test
doctl compute domain records list kobolabs.dev | grep espo-test   # note its ID
doctl compute domain records delete kobolabs.dev <ID>
```

And on the Kobo test account, the projects named "... (espo-kobo test)" if they're no
longer wanted.

# Manual steps

Everything else is scripted (`deploy/up.sh`, `espo/seed/seed.py`, kobo-espo-bridge's `setup.py`
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
   ("Send access info"; needs outgoing email, below) or set one and send it separately.
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

- **Outgoing email** (the test droplet uses Resend; DigitalOcean blocks ports 465 and 587).
  `espo/seed/seed.py` does steps 2-4 when `secrets/resend.key` is there; by hand:
  1. In Resend, verify the sending domain (its DKIM, SPF and MX records in DNS) and make
     an API key with sending access only.
  2. Administration → Outbound Emails: from address (e.g. `noreply@respond.kobolabs.dev`),
     from name ("Kobo Respond"), SMTP `smtp.resend.com`, port 2587, TLS, username
     `resend`, password the API key.
  3. Administration → Group Email Accounts → Create, with the **same address**: status
     Active, IMAP off, SMTP on with the same server, port, TLS, username and key. This
     EspoCRM sends its own emails (access info, notifications) through the group account
     whose address is the from address; the Outbound Emails page's SMTP alone sends only
     its "Send Test Email". Leave "Shared" off, so nobody sends as `noreply`.
  4. Administration → Notifications: "Email notifications upon assignment" (entities
     Task, Case, CApplication, CProject, CResponse, CSite) and "...mentions in posts".
  Test users' addresses are Resend's test inbox (`delivered+<username>@resend.dev`): it
  accepts everything and never bounces, which would hurt the domain's standing.
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
doctl compute domain records list kobolabs.dev | grep -E "staging.respond|espo-test"   # note their IDs
doctl compute domain records delete kobolabs.dev <ID>
```

And on the Kobo test account, the projects named "... (espo-kobo test)" if they're no
longer wanted.

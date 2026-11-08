# EspoCRM in Kobo's look and feel

Status: 2026-11-08. Built and checked locally (phases 0–2); the droplet and the manual next.

## Goal

Someone who uses KoboToolbox (KPI) or reads kobotoolbox.org opens EspoCRM and sees the same
family: Kobo's logo, Kobo's blues and greys, the same font. It stays EspoCRM. The layout,
the navbar, the icons and the screens don't change. It should be a light touch, so that an
EspoCRM upgrade can't break it and nobody has to maintain a fork of EspoCRM's theme.

Out of scope: per-response or per-team branding (one look for the instance), Lora
headings, KPI's dark top bar, restyling individual EspoCRM components, dark mode.

## Where the Kobo look comes from

The two sources agree on the parts that matter:

| | KPI (`../kpi/jsapp/scss/colors.scss`, `js/theme/kobo/index.ts`) | kobotoolbox.org (`kobo_website/_assets/styles/setup/`) |
|---|---|---|
| Primary | `$kobo-blue` #2095f3, hover #1977c2 | #2095f3, hover #408deb |
| Dark blue (links, text accents) | #135991 | #00599d |
| Light blue backgrounds | #d2e9fc, #e8f4fd | #c0e3ff, #e8f4ff |
| Teal | #52c5d0, dark #1b5e64 | #52c5d0, dark #1c6d74 |
| Greys (text → background) | #333847, #5a627d, #a6acbf, #e1e3ea, #edeef2, #f9f9fb | #333847, #565e76, #979fb4, #e7e9ee, #f3f4f6, #f9f9fb |
| Red / amber / green | #9d0000, #ffbe80, #178949 | similar |
| Font | Roboto | Inter (headings Lora) |
| Radius | 6px buttons | 6px buttons |

The manual (`site/static/site/home.css`) already follows the website: Inter, #2095f3,
#00599d, and the website's logo in `site/static/site/logo.svg`.

Where they differ, use the **website's** value, because the manual already does.
For the blues, use **KPI's**, the product people use every day. The two are within a few
percent of each other anyway.

## What EspoCRM gives us

EspoCRM 10's default theme ("Espo", which the droplet uses) is built on about 430 CSS
custom properties on `:root` (checked against the droplet's `client/css/espo/espo.css`):
`--brand-primary`, `--btn-primary-*`, `--link-color`, `--navbar-*`, `--body-bg`,
`--default-border-color`, `--default-heading-bg-color`, `--input-border-focus`,
`--font-family`, and so on. It already uses **Inter**, so the font matches the website with
no work.

So the whole look is **one small stylesheet that only redefines variables**. It doesn't copy
EspoCRM's theme and doesn't override selectors. Add to that the company logo and the
application name, which are ordinary Settings.

## The changes (as built)

All of it is in `espo/look/`, mounted from the repo by `docker-compose.yml`:

```
espo/look/module/                 an EspoCRM module, KoboLook (custom/Espo/Modules/KoboLook)
  Resources/module.json
  Resources/metadata/app/client.json     cssList (+ kobo.css), favicon, faviconAlternate
  Resources/metadata/themes/Espo.json    logo: the light theme's logo
espo/look/client/                 client/custom/kobo-look/
  kobo.css                        variables only
  logo.svg                        the website's logo for light backgrounds (as the manual's)
  favicon.svg, favicon.png        KPI's Kobo symbol and favicon
```

### 1. `kobo.css`, variables only (about 70 lines)

A `:root { … }` block with Kobo values for:

- **Primary and buttons:** `--brand-primary` #2095f3, hover #1977c2, pressed #135991;
  `--brand-primary-lighten-*` #8fcaf9 / #d2e9fc.
- **Links:** #135991, hover #1977c2. Links to records are in Kobo's text grey.
- **Text:** #333847 (KPI's "active text"), grey text #5a627d, muted #828ba5.
- **Surfaces and lines:** body and navbar #edeef2 (KPI's sidebar), panel headings
  #e8f4fd, borders #e1e3ea, striped rows #f9f9fb.
- **Navbar:** hover #e1e3ea, the active tab #d2e9fc.
- **Inputs:** border #cacdd9, focus #2095f3.
- **Status labels** (`--state-*`, a pale background with dark text, as on Case statuses):
  primary #e8f4fd/#135991, success #e3f9db/#178949, danger #ffe9e9/#9d0000,
  warning #ffe8cc/#803f00, info #eef0f6/#4f608d. The solid labels (Urgent and High
  priority, `--brand-danger/-warning`) keep EspoCRM's colours. Kobo's #9d0000 is too dark
  for a solid badge.

### 2. Loading it: a module, not Settings

EspoCRM 10 merges a module's metadata with its own:

- `app.client.cssList` adds stylesheets after the theme's (`ClientManager.php`).
- `app.client.favicon` and `faviconAlternate` replace the favicon.
- `themes.Espo.logo` is the logo the navbar and login page show **when no company logo
  is set** (`getLogoSrc()`). So the seed doesn't upload a logo, and a logo set by hand
  in Administration still wins. It can also be an SVG.

The two folders are bind mounts in `docker-compose.yml`. They're kept separate from
Entity Manager's `custom/Espo/Custom/`. They aren't `:ro`, because the image's entrypoint
chowns `custom/` and `client/custom/` and stops if it can't. `deploy/up.sh` already rsyncs
the repo.

### 3. Theme, from `deploy/up.sh`, not the seed

After `compose up`, `deploy/up.sh` runs `bin/command config:set theme Espo`,
`config:set userThemesDisabled true --type=bool` and `clear-cache`. The variables are for
the light theme, so a user on Dark would get light greys. `applicationName` stays as the
seed sets it.

### 4. Not doing

- KPI's dark top bar (#333847). It would mean overriding all the `--navbar-inverse-*`
  variables and logo contrast. Kobo's light greys look like KPI's sidebar and the website's
  white header, with half the overrides.
- Lora for headings. That's a marketing-site font. In an app it would make page titles look
  out of place next to KPI.
- The solid priority badges, chart colours, and anything that isn't a variable.
- The extension (`plans/espo-extension-plan.md`). Kobo's look is kobo-espo's own
  configuration, so it stays here. If kobo-in-a-box wants the same look, the module moves
  into the extension as it is.

## Phases

0. **Checked** on a local stack (`docker compose -p kobo-look`, port 8086), 2026-11-08:
   `cssList`, `favicon` and the theme's `logo` all work as above in 10.0.11. Changing the
   favicon needs no edits to EspoCRM's own files.
1. **Done.** The stylesheet was compared before and after on the login page, the Case list
   (statuses and priorities), a Case's detail page and its edit form (focused input, Save).
   It's still clearly EspoCRM, in Kobo's colours.
2. **Done.** Bind mounts, `deploy/up.sh`, and `tests/cases/look.py` (8/8 locally).
3. **Droplet:** `deploy/up.sh`, then `tests/cases/look.py`. Check by eye as admin and as a
   cluster partner.
4. **Manual:** the screenshots in `site/` show the old colours. Rerun `site/demo-data.py`
   and `site/shots.py`, then `site/build.py`. Add a line on the "Running it" page about
   `espo/look/`.

## Tests

`tests/cases/look.py` reads only (it's in `run_all.sh`):

- L1: `kobo.css` is served and sets `--brand-primary: #2095f3`; the logo and favicons are served.
- L2: the page loads it after EspoCRM's stylesheet, and the favicon is Kobo's.
- L3: `themes.Espo.logo` in the metadata is Kobo's.
- L4: `theme` is Espo and `userThemesDisabled` is on.

Whether it *looks* right is a human check (phase 1), not a test.

## Risks

- **EspoCRM upgrades rename variables.** The CSS only sets variables, so the worst case is
  that some colours fall back to EspoCRM's defaults. Nothing breaks. Recheck after each
  upgrade with the phase 1 screens.
- **Contrast:** white on #2095f3 is about 3.1:1, below WCAG AA for normal text. KPI and the
  website accept that for buttons. Keep links and text on the darker #135991 / #333847,
  which pass.

#!/usr/bin/env python3
"""The CSO mapping forms (Workflow F, plans/cso-mapping-plan.md), from the Kobo and WHO
draft (ref/Draft CSO mapping tool v1.docx):

    python3 -I kobo/forms/cso.py [--cholera] [--identity]

writes, for each country with forms of its own (COUNTRIES), cso-profile-<iso3>.json and
cso-update-<iso3>.json (and their bridge templates, kobo/templates/ of the same names), places asked as a cascade of its admin areas (areas.csv, EspoCRM's
list, P-codes from the geocoder); and for every other country the generic
cso-profile.json and cso-update.json, places asked as the country and a geopoint (P-coded
afterwards, the plan's step 3). The choices come from workflows/cso/lists/cso-lists.json, as
EspoCRM's enums do, so the two always agree. --cholera asks the cholera roles in place of
the general ones (files ...-cholera.json); --identity asks the draft's Q2 split (Q2 the
main type, a select-all for identity).

The code and key (cso, key) come in the link a CSO is emailed (?d[/data/cso]=CSO-...),
so a profile sent again updates the same CSO and an update is the CSO's own.
"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
LISTS = json.loads((HERE.parents[1] / 'workflows' / 'cso' / 'lists' / 'cso-lists.json').read_text())
# Countries with forms of their own: the labels of their admin levels (the geocoder's levels)
COUNTRIES = {'KEN': {'name': 'Kenya', 'admin1': 'County', 'admin2': 'Sub-county'}}
EMAIL = r"regex(., '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')"


def options(name):
    v = LISTS[name]
    return v['choices'] if isinstance(v, dict) else v


def q(type_, name, label, **kw):
    return {k: v for k, v in {'type': type_, 'name': name, 'label': label, **kw}.items() if v is not None}


def pick(name, label, list_name, many=False, at_most=None, required=True, other=True, **kw):
    """A select question and, when its list has 'other', the text that says what."""
    rows = [q(f'select_{"multiple" if many else "one"} {list_name}', name, label,
              required='true' if required else None, **kw)]
    if at_most:
        rows[0].update(constraint=f'count-selected(.) <= {at_most}', constraint_message=f'Choose at most {at_most}.',
                       hint=kw.get('hint') or f'Choose up to {at_most}.')
    if other and any(c['code'] == 'other' for c in options(list_name)):
        test = f"selected(${{{name}}}, 'other')" if many else f"${{{name}}} = 'other'"
        rows.append(q('text', f'{name}_other', 'Please specify', required='true', relevant=test))
    return rows


def group(name, label, rows, repeat=False):
    kind = 'repeat' if repeat else 'group'
    return [{'type': f'begin_{kind}', 'name': name, 'label': label}, *rows, {'type': f'end_{kind}'}]


def head():
    return [q('start', 'start', None), q('end', 'end', None),
            q('hidden', 'cso', None), q('hidden', 'key', None)]


def place_rows(country, required_admin2):
    """Where: a cascade of the country's admin areas, or (generic) the country and a pin.
    `area` is the deepest P-code given (the bridge links the admin area by it)."""
    if country:
        c = COUNTRIES[country]
        return [q('select_one_from_file areas.csv', 'admin1', c['admin1'], required='true',
                  choice_filter="level='admin1'", appearance='minimal'),
                q('select_one_from_file areas.csv', 'admin2', c['admin2'], required='true' if required_admin2 else None,
                  choice_filter='parent=${admin1}', appearance='minimal'),
                q('calculate', 'area', None, calculation="if(${admin2} != '', ${admin2}, ${admin1})"),
                q('hidden', 'country', None, default=country)]
    return [*pick('country', 'Country', 'countries', other=False, appearance='minimal autocomplete'),
            q('geopoint', 'location', 'Drop a pin in the place', required='true',
              hint='Anywhere in the district or area: it is matched to the admin area it falls in.')]


def profile(country, cholera, identity):
    types = options('cso_types')
    if identity:
        idents = {c['code'] for c in options('identities')}
        types = [c for c in types if c['code'] not in idents]
    roles = 'roles_cholera' if cholera else 'roles'
    where = country and COUNTRIES[country]['name']
    survey = [
        *head(),
        q('note', 'intro', 'This profile maps civil society organisations working on health emergencies, '
          'so that WHO and partners can coordinate and CSOs can connect with one another. '
          'It takes about 15 minutes. You can send it again later to update it.'),
        *group('about', 'About the organization', [
            q('text', 'cso_name', 'What is the official name of your organization?', required='true'),
            q('text', 'acronym', 'Commonly used acronym, if any'),
            *pick('cso_type', 'Which type of civil society organization best describes your organization?', 'cso_types'),
            *(pick('identity', 'Does any of these also describe your organization?', 'identities', many=True,
                   required=False, other=False) if identity else []),
            *pick('country_registered', 'In which country is your organization headquartered or formally registered?',
                  'countries', other=False, appearance='minimal autocomplete', default=country),
            *pick('levels', 'At what level does your organization mainly operate?', 'levels', many=True),
        ]),
        *group('FOCAL_POINTS', 'Focal point for this mapping', [
            q('text', 'name', 'Name', required='true'),
            q('text', 'position', 'Position'),
            q('text', 'email', 'Email', required='true', constraint=EMAIL, constraint_message='An email address, please.'),
            q('text', 'phone', 'Telephone/WhatsApp', hint='With the country code, e.g. +254 712 345678'),
        ], repeat=True),
        q('note', 'focal_more', 'Add a second focal point (the + button) so the profile still reaches someone '
          'if one person leaves.'),
        *pick('sharing', "May the organization's profile and designated contact details be shared with other "
              'participating CSOs and authorized partners for coordination and collaboration?', 'sharing', other=False),
        *group('where', 'Where the organization works', [
            *group('PRESENCE', f'A place where your organization has an operational presence{f" in {where}" if where else ""}',
                   place_rows(country, required_admin2=False), repeat=True),
            *([q('select_multiple countries', 'other_countries', f'Other countries where your organization works, besides {where}')]
              if country else []),
            *pick('settings', 'Which types of settings can your organization reach?', 'settings', many=True),
            *pick('populations', 'Which population groups or communities does your organization principally work with?',
                  'populations', many=True),
        ]),
        *group('does', 'What the organization does', [
            *pick('stages', 'In which stages of health emergency management does your organization currently work or has worked?',
                  'stages', many=True),
            *pick('roles', 'What roles or activities does your organization currently undertake or has undertaken in '
                  'health emergencies?', roles, many=True),
            *pick('hazards', 'For which hazards, diseases or emergency contexts does your organization have experience '
                  'or current activities?', 'hazards', many=True),
            *pick('roles_with_support', 'Which of these roles could your organization undertake if additional support '
                  'or resources were available?', roles, many=True, required=False),
        ]),
        *group('coordination', 'Coordination, capacity and collaboration', [
            *pick('mechanisms', 'In which coordination or decision-making mechanisms does your organization currently '
                  'participate?', 'mechanisms', many=True,
                  constraint="not(selected(., 'none') and count-selected(.) > 1)",
                  constraint_message='"Not currently participating" goes alone.'),
            *pick('offers', 'What could your organization offer other CSOs or partners?', 'exchange', many=True, at_most=3),
            *pick('seeks', 'What support, expertise or partnership is your organization currently seeking?', 'exchange',
                  many=True, at_most=3, required=False),
            *pick('connect_via', 'How would your organization prefer to connect and exchange information with other CSOs?',
                  'connect_via', many=True),
        ]),
    ]
    lists = {'cso_types': types}
    return survey, lists


def update(country, cholera):
    roles = 'roles_cholera' if cholera else 'roles'
    survey = [
        *head(),
        q('note', 'intro', 'A short update on what your organization is doing in one place. Send one per place.'),
        q('text', 'cso_typed', 'Your organization\'s CSO code', required='true', relevant="${cso} = ''",
          hint='CSO- and 4 characters, in the email you got after sending your profile.',
          constraint="regex(., '^CSO-[2-9A-HJKMNP-TV-Z]{4}$')", constraint_message='A code like CSO-7K3Q.'),
        q('calculate', 'cso_code', None, calculation="if(${cso} != '', ${cso}, ${cso_typed})"),
        *group('place', 'Where is this activity being implemented?', [
            *place_rows(country, required_admin2=True),
            q('text', 'locality', 'Locality (village, town or neighbourhood)'),
            *([q('geopoint', 'location', 'Location (optional)')] if country else []),
        ]),
        *pick('roles', 'What activity or service are you currently providing in this location?', roles, many=True),
        *pick('status', 'What is the current status?', 'update_status', other=False),
        *pick('populations', 'Which population groups are being reached?', 'populations', many=True),
        q('text', 'facility', 'Facility being reached, if any (its name)'),
        *pick('needs', 'What is the principal operational gap or collaboration need in this location?', 'exchange',
              many=True, at_most=3, required=False),
        q('text', 'needs_note', 'A short explanation of the need', relevant="count-selected(${needs}) > 0"),
    ]
    return survey, {}


def choices(survey, extra):
    used = []
    for row in survey:
        t = row['type'].split()
        if t[0] in ('select_one', 'select_multiple') and t[1] not in used:
            used.append(t[1])
    return [{'list_name': name, 'name': c['code'], 'label': c['label']}
            for name in used for c in (extra.get(name) or options(name))]


# Kobo question -> EspoCRM field, and its type for the bridge (multiEnum splits the answer)
PROFILE_FIELDS = [('key', 'keyGiven', None), ('acronym', 'acronym', None), ('cso_type', 'csoType', None),
                  ('cso_type_other', 'csoTypeOther', None), ('identity', 'identities', 'multiEnum'),
                  ('country_registered', 'countryRegistered', None), ('other_countries', 'otherCountries', 'multiEnum'),
                  ('levels', 'levels', 'multiEnum'), ('sharing', 'sharing', None),
                  ('settings', 'settings', 'multiEnum'), ('settings_other', 'settingsOther', None),
                  ('populations', 'populations', 'multiEnum'), ('populations_other', 'populationsOther', None),
                  ('stages', 'stages', 'multiEnum'), ('roles', 'roles', 'multiEnum'), ('roles_other', 'rolesOther', None),
                  ('hazards', 'hazards', 'multiEnum'), ('hazards_other', 'hazardsOther', None),
                  ('roles_with_support', 'rolesWithSupport', 'multiEnum'), ('roles_with_support_other', 'rolesWithSupportOther', None),
                  ('mechanisms', 'mechanisms', 'multiEnum'), ('mechanisms_other', 'mechanismsOther', None),
                  ('offers', 'offers', 'multiEnum'), ('offers_other', 'offersOther', None),
                  ('seeks', 'seeks', 'multiEnum'), ('seeks_other', 'seeksOther', None),
                  ('connect_via', 'connectVia', 'multiEnum'), ('connect_via_other', 'connectViaOther', None)]
UPDATE_FIELDS = [('key', 'keyGiven', None), ('locality', 'locality', None), ('roles', 'roles', 'multiEnum'),
                 ('roles_other', 'rolesOther', None), ('status', 'status', None), ('populations', 'populations', 'multiEnum'),
                 ('populations_other', 'populationsOther', None), ('facility', 'facility', None),
                 ('needs', 'needs', 'multiEnum'), ('needs_other', 'needsOther', None), ('needs_note', 'needsNote', None)]
CHOLERA = {'roles': 'rolesCholera', 'roles_other': 'rolesCholeraOther', 'roles_with_support': 'rolesWithSupportCholera',
           'roles_with_support_other': 'rolesWithSupportOther'}


def fields(pairs, cholera, table='field'):
    out = []
    for kobo, espo, kind in pairs:
        espo = CHOLERA.get(kobo, espo) if cholera else espo
        out.append(f'[[{table}]]\nkobo = "{kobo}"\nespo = "{espo}"' + (f'\ntype = "{kind}"' if kind else '') + '\n')
    return out


def place_fields(country, table):
    """Where, for the bridge: the area by its P-code (a country's form), or the country and
    the pin as numbers (the generic form; P-coded afterwards)."""
    rows = [f'[[{table}]]\nkobo = "country"\nespo = "country"\n']
    if country:
        rows.append(f'[[{table}]]  # the deepest P-code given\nkobo = "area"\nespo = "adminArea"\ntype = "link"\n'
                    'entity = "CAdminArea"\nlookup = "pcode"\n')
    rows.append(f'[[{table}]]  # as numbers, for the P-coding step and the maps\nkobo = "location"\n'
                'latitude = "latitude"\nlongitude = "longitude"\n')
    return rows


def template(kind, stem, title, country, cholera):
    """The bridge template of a form cso.py wrote: generated with it, so the two agree."""
    user = f'kobo-{stem}'
    secret = 'ESPO_' + stem.upper().replace('-', '_') + '_API_KEY'
    head = [f'# Workflow F (plans/cso-mapping-plan.md). Generated by kobo/forms/cso.py with its form,\n'
            f'# kobo/forms/{stem}.json: change them there.',
            f'[bridge]\nuser = "{user}"\nrole = "Kobo {stem}"\nsecret = "{secret}"\n',
            f'[form]\nname = "{title} (espo-kobo test)"\n']
    areas = ([f'[[list]]  # the country\'s admin areas, for the cascade\nfile = "areas.csv"\nentity = "CAdminArea"\n'
              f'where = {{ country = "{country}" }}\norder_by = "pcode"\n'
              'columns = { name = "pcode", label = "name", level = "level", parent = "parentPcode" }\n'
              f'forms = ["{title} (espo-kobo test)"]\n'] if country else [])
    if kind == 'profile':
        body = ['# A CSO\'s profile (CCso): how a CSO registers. Kept current in the CSO portal after that;\n'
                '# sent again from the link in its email (its code and key), it updates the same CSO,\n'
                '# its places from Kobo the new submission\'s (the portal\'s stay).\n'
                '[record]\nentity = "CCso"\npanel = "Profile"\nname = "{cso_name}"\nmatch = { code = "cso" }\n'
                'required = ["cso_name", "cso_type", "sharing"]\n',
                *fields(PROFILE_FIELDS, cholera),
                '# Its focal points: Contacts of the CSO (and its Account, formula), one per person and CSO\n'
                '# by email, so the same person sent again is the same Contact (and someone in two CSOs\n'
                '# is a contact of each). Kept in the portal from then on\n'
                '[[repeat]]\ngroup = "FOCAL_POINTS"\nentity = "Contact"\nlink = "cCso"\nname = "{name}"\n'
                'match = { emailAddress = "email", cCsoId = "@record" }\n',
                '[[repeat.field]]\nkobo = "name"\nespo = "name"\ntype = "personName"\n',
                *fields([('email', 'emailAddress', None), ('phone', 'phoneNumber', None), ('position', 'title', None)],
                        cholera, 'repeat.field'),
                '[[repeat]]\ngroup = "PRESENCE"\nentity = "CPresence"\nlink = "cso"\nname = "{cso_name}"  # then the place\'s (formula)\n',
                *place_fields(country, 'repeat.field')]
    else:
        body = ['# A CSO\'s update in one place (CCsoUpdate), its CSO by the code in its link (or typed)\n'
                '[record]\nentity = "CCsoUpdate"\npanel = "Update"\nname = "{cso_code}"  # then the CSO\'s and the place\'s (formula)\n'
                'required = ["cso_code", "roles", "status"]\n',
                '[[field]]\nkobo = "cso_code"\nespo = "cso"\ntype = "link"\nentity = "CCso"\nlookup = "code"\n',
                *fields(UPDATE_FIELDS, cholera), *place_fields(country, 'field')]
    out = HERE.parent / 'templates' / f'{stem}.toml'
    out.write_text('\n'.join(head + body + areas))
    print(f'{out.relative_to(HERE.parent.parent)}')


def write(stem, title, form_id, survey, extra):
    form = {'settings': {'form_title': f'{title} (espo-kobo test)', 'form_id': form_id, 'version': '1',
                         'style': 'pages'},
            'survey': survey, 'choices': choices(survey, extra)}
    out = HERE / f'{stem}.json'
    out.write_text(json.dumps(form, indent=1, ensure_ascii=False) + '\n')
    print(f'{out.name}: {len(survey)} rows, {len(form["choices"])} choices')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cholera', action='store_true', help='the cholera roles in place of the general ones')
    ap.add_argument('--identity', action='store_true', help="the draft's Q2 split: main type, and identity as a select-all")
    args = ap.parse_args()
    tail = '-cholera' if args.cholera else ''
    label = ' (cholera)' if args.cholera else ''
    for country in [*COUNTRIES, None]:
        suffix = f'-{country.lower()}' if country else ''
        where = f': {COUNTRIES[country]["name"]}' if country else ''
        for kind, make in (('profile', lambda: profile(country, args.cholera, args.identity)),
                           ('update', lambda: update(country, args.cholera))):
            stem, title = f'cso-{kind}{suffix}{tail}', f'CSO {kind}{where}{label}'
            write(stem, title, stem.replace('-', '_'), *make())
            template(kind, stem, title, country, args.cholera)


if __name__ == '__main__':
    main()

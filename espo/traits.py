"""Formula traits (plans/workflow-packs-plan.md, 3): the patterns several workflows' formulas
share, as snippets with parameters, switched on per entity in a pack's workflow.toml. A
pack's own formula block is then only what is particular to it.

    [traits.CPresence]
    portal_default = { field = "csoId", from = "cCsoId" }   # made in a portal: the CSO of
                                                            # whoever made it (their contact's)
    pcodes = "adminArea"            # the area from a P-coded pin; pcode1..3 and country up the
                                    # area's parents; pcodeStatus (given, pending)
    inherit = [                     # its parent's teams and fields, when the link is set or
                                    # changes (or one of `also`); cascade: the parent's
                                    # changes follow to it
      { link = "cso", entity = "CCso", copy = ["teamsIds", "accountId"], cascade = true, also = ["country"] },
      { link = "response", entity = "CResponse", copy = ["teamsIds"], unless = "project" },
    ]
    supersede = { by = ["csoId", "adminAreaId"], counted = { field = "keyCheck", in = ["ok", "confirmed"] } }
                                    # the latest counted record of each `by` is the current one
    [traits.CPresence.checks]       # data checks: a dataChecks option each, and when it's set
    outside = "pcodeStatus == 'outside'"

    [traits.CResponder]
    teams_up = { link = "account", entity = "Account" }   # its parent's teams: its own and its
                                    # siblings' (the parent it left: the others'), written when
                                    # its teams or its parent change
    teams_from_clusters = { clusters = "clusters" }       # a response's record: the response's
                                    # teams and those of its cluster projects in its sectors
                                    # (all = true: every project's); a new project, or one whose
                                    # cluster changes, gives its teams to them (on CProject)
    account_from_organisation = { organisation = "organisation", other = "organisationOther",
                                  acronym = "acronym", type = "orgType" }
                                    # its organisation's Account: the one linked to its list
                                    # entry, else the unlisted one of the typed name; made if none

    [traits.CFocalPoint]
    find_or_make_contact = { account = "account", email = "emailAddress", phone = "phone",
                             name = "name", title = "jobTitle" }
                                    # its person: the Contact on its Account with its email (else
                                    # its phone), made if none; linked (contact), the Contact's
                                    # blank phone and title filled

Where they go in the Before Save Custom Script: portal_default, pcodes, inherit,
teams_from_clusters, account_from_organisation and find_or_make_contact before the packs' blocks; checks,
supersede, teams_up, the cascades (the parent's side of an inherit with `cascade`) and the
cluster teams (the project's side of teams_from_clusters) after them. A block with a line `// trait: <name>` has that trait there instead
(e.g. a link the block finds first, then inherit).
"""

BEFORE = ('portal_default', 'pcodes', 'inherit', 'teams_from_clusters', 'account_from_organisation', 'find_or_make_contact')
AFTER = ('checks', 'supersede', 'teams_up', 'cascade', 'cluster_teams')
TRAITS = BEFORE + AFTER[:-2]  # cascade and cluster_teams are made from other traits, not named
ROWS = 1000  # the most child records a cascade or supersede reads


def q(s):
    return "'" + str(s).replace('\\', '\\\\').replace("'", "\\'") + "'"


def changed(attrs, new=True):
    return ' || '.join((["entity\\isNew()"] if new else []) + [f"entity\\isAttributeChanged({q(a)})" for a in attrs])


def portal_default(t, entity):
    f = t['field']
    return f"""// Made in a portal: the {f} of whoever made it (their own contact's) (trait portal_default)
if (!{f} && entity\\isNew() && env\\userAttribute('type') == 'portal' && env\\userAttribute('contactId')) {{
    {f} = record\\attribute('Contact', env\\userAttribute('contactId'), {q(t['from'])});
}}"""


def pcodes(t, entity):
    """t: the area link's name, or { area, pins = false } for records with no pin (areas
    picked from a list): no pcodeStatus, no P-coding step."""
    area, pins = (t, True) if isinstance(t, str) else (t['area'], t.get('pins', True))
    a = f'{area}Id'
    pin = f"""// Where (trait pcodes): from a P-coded pin, the area of the deepest P-code the P-coding
// step found that EspoCRM has (a country's areas may be loaded to fewer levels than the
// geocoder knows); the area's P-codes up its parents, and its country
if (!{a} && pcodeStatus == 'done') {{
    if (pcode3) {{
        {a} = record\\findOne('CAdminArea', 'createdAt', 'asc', 'pcode=', pcode3);
    }}
    if (!{a} && pcode2) {{
        {a} = record\\findOne('CAdminArea', 'createdAt', 'asc', 'pcode=', pcode2);
    }}
    if (!{a} && pcode1) {{
        {a} = record\\findOne('CAdminArea', 'createdAt', 'asc', 'pcode=', pcode1);
    }}
}}
""" if pins else "// Where (trait pcodes): the area's P-codes up its parents, and its country\n"
    given = f"""
    if (pcodeStatus != 'done') {{
        pcodeStatus = 'given';
    }}""" if pins else ''
    pending = f"""
// A pin not P-coded yet: the P-coding step's work
if (!{a} && latitude != null && !pcodeStatus) {{
    pcodeStatus = 'pending';
}}""" if pins else ''
    return pin + f"""if ({a} && ({changed([a])})) {{
    $a = {a};
    $n = 0;
    while ($a && $n < 5) {{
        $level = record\\attribute('CAdminArea', $a, 'level');
        if ($level == 'admin1') {{
            pcode1 = record\\attribute('CAdminArea', $a, 'pcode');
        }} else if ($level == 'admin2') {{
            pcode2 = record\\attribute('CAdminArea', $a, 'pcode');
        }} else if ($level == 'admin3') {{
            pcode3 = record\\attribute('CAdminArea', $a, 'pcode');
        }}
        $parent = record\\attribute('CAdminArea', $a, 'parentPcode');
        $a = ifThenElse($level != 'admin0' && $parent, record\\findOne('CAdminArea', 'createdAt', 'asc', 'pcode=', $parent), null);
        $n = $n + 1;
    }}
    country = record\\attribute('CAdminArea', {a}, 'country');{given}
}}{pending}"""


def copy_lines(source, idvar, copy, indent='    '):
    out = []
    for f in copy:
        if f == 'teamsIds':  # a parent without teams leaves its own
            out += [f"{indent}$teams = record\\attribute({q(source)}, {idvar}, 'teamsIds');",
                    f"{indent}if (array\\length($teams) > 0) {{", f"{indent}    teamsIds = $teams;", f"{indent}}}"]
        else:
            out.append(f"{indent}{f} = record\\attribute({q(source)}, {idvar}, {q(f)});")
    return out


def inherit(entries, entity):
    out = []
    for e in entries:
        link = f"{e['link']}Id"
        unless = f"!{e['unless']}Id && " if e.get('unless') else ''
        out += [f"// Its {e['link']}'s: {', '.join(e['copy'])} (trait inherit)",
                f"if ({unless}{link} && ({changed([link, *e.get('also', [])])})) {{", *copy_lines(e['entity'], link, e['copy']), '}']
    return '\n'.join(out)


def checks(table, entity):
    out = ["// Data checks: what looks wrong, as flags (dataChecks' options) for the people who check",
           "// the data. Never a refusal: a report is kept, then fixed or explained (trait checks)",
           "$checks = list();"]
    for code, when in table.items():
        out += [f"if ({when}) {{", f"    $checks = array\\push($checks, {q(code)});", '}']
    return '\n'.join(out + ['dataChecks = $checks;'])


def supersede(t, entity):
    by = list(t['by'])
    c = t.get('counted')
    if c:
        own = ' || '.join(f"{c['field']} == {q(v)}" for v in c['in'])
        other = f"($oc == {' || $oc == '.join(q(v) for v in c['in'])})"
        get = f"        $oc = record\\attribute({q(entity)}, $o, {q(c['field'])});\n"
        watch = by + [c['field']]
    else:
        own, other, get, watch = 'true', 'true', '', by
    where = ', '.join(f"{q(b + '=')}, {b}" for b in by)
    return f"""// The latest counted record of each {' and '.join(by)} is the current one: a newer one marks the
// others superseded (trait supersede)
$counted = {own};
if ({' && '.join(by)} && $counted && ({changed(watch)})) {{
    superseded = false;
    $others = record\\findMany({q(entity)}, {ROWS}, 'createdAt', 'asc', {where});
    $i = 0;
    while ($i < array\\length($others)) {{
        $o = array\\at($others, $i);
{get}        if ($o != id && {other}) {{
            if (entity\\isNew() || datetime\\diff(createdAt, record\\attribute({q(entity)}, $o, 'createdAt'), 'seconds') > 0) {{
                if (!record\\attribute({q(entity)}, $o, 'superseded')) {{
                    record\\update({q(entity)}, $o, 'superseded', true, 'current', false);
                }}
            }} else {{
                superseded = true;
            }}
        }}
        $i = $i + 1;
    }}
}}
current = $counted && !superseded;"""


def teams_up(t, entity):
    link, parent = f"{t['link']}Id", t['entity']
    def union(start, pid):
        return f"""    $teams = {start};
    $rows = record\\findMany({q(entity)}, {ROWS}, 'createdAt', 'asc', {q(link + '=')}, {pid});
    $i = 0;
    while ($i < array\\length($rows)) {{
        $o = array\\at($rows, $i);
        if ($o != id) {{
            $add = record\\attribute({q(entity)}, $o, 'teamsIds');
            $j = 0;
            while ($j < array\\length($add)) {{
                if (!array\\includes($teams, array\\at($add, $j))) {{
                    $teams = array\\push($teams, array\\at($add, $j));
                }}
                $j = $j + 1;
            }}
        }}
        $i = $i + 1;
    }}
    record\\update({q(parent)}, {pid}, 'teamsIds', $teams);"""
    return f"""// Its {t['link']}'s teams: its own and its {t['link']}'s other {entity} records' (trait teams_up)
if ({link} && ({changed(['teamsIds', link])})) {{
{union("ifThenElse(teamsIds, teamsIds, list())", link)}
}}
// The {t['link']} it left: the others' teams
if (!entity\\isNew() && entity\\isAttributeChanged({q(link)}) && entity\\attributeFetched({q(link)})) {{
    $left = entity\\attributeFetched({q(link)});
{union("list()", "$left")}
}}"""


def union_into(var, source, indent):
    """Formula lines adding the ids of the list `source` to the list variable `var`."""
    lines = [f"$add = {source};", "$j = 0;", "while ($j < array\\length($add)) {",
             f"    if (!array\\includes({var}, array\\at($add, $j))) {{",
             f"        {var} = array\\push({var}, array\\at($add, $j));", "    }", "    $j = $j + 1;", "}"]
    return '\n'.join(indent + x for x in lines)


def teams_from_clusters(t, entity):
    clusters = t.get('clusters', 'clusters')
    which = 'projects' if t.get('all') else f'projects in its sectors ({clusters})'
    cond = 'true' if t.get('all') else f"array\\includes({clusters}, record\\attribute('CProject', $p, 'cluster'))"
    watch = ['responseId'] + ([] if t.get('all') else [clusters])
    return f"""// In its response's teams and those of the response's {which}: those clusters' people
// see it, and the coordinators (trait teams_from_clusters)
if (responseId && ({changed(watch)})) {{
    $teams = record\\attribute('CResponse', responseId, 'teamsIds');
    $projects = record\\findMany('CProject', 200, 'createdAt', 'asc', 'responseId=', responseId);
    $i = 0;
    while ($i < array\\length($projects)) {{
        $p = array\\at($projects, $i);
        if ({cond}) {{
{union_into('$teams', "record\\attribute('CProject', $p, 'teamsIds')", ' ' * 12)}
        }}
        $i = $i + 1;
    }}
    if (array\\length($teams) > 0) {{
        teamsIds = $teams;
    }}
}}"""


def cluster_teams(children, entity):
    """The project's side of teams_from_clusters: (child, its clusters field, or None for
    every project's)."""
    out = []
    for child, clusters in children:
        cond = 'true' if clusters is None else f"array\\includes(record\\attribute({q(child)}, $o, {q(clusters)}), cluster)"
        out.append(f"""// A new project, or its cluster changed: the response's {child} records {'(all)' if clusters is None else 'in that cluster'}
// get its teams (trait teams_from_clusters, {child}'s)
if (responseId && cluster && (entity\\isNew() || entity\\isAttributeChanged('cluster'))) {{
    $rows = record\\findMany({q(child)}, {ROWS}, 'createdAt', 'asc', 'responseId=', responseId);
    $i = 0;
    while ($i < array\\length($rows)) {{
        $o = array\\at($rows, $i);
        if ({cond}) {{
            $have = record\\attribute({q(child)}, $o, 'teamsIds');
{union_into('$have', 'teamsIds', ' ' * 12)}
            record\\update({q(child)}, $o, 'teamsIds', $have);
        }}
        $i = $i + 1;
    }}
}}""")
    return '\n'.join(out)


def account_from_organisation(t, entity):
    org, other = f"{t.get('organisation', 'organisation')}Id", t.get('other', 'organisationOther')
    extra = ''.join(f", {q(a)}, {v}" for a, v in (
        ('cAcronym', t.get('acronym')),
        ('cOrgType', f"ifThenElse($listed, record\\attribute('COrganisation', {org}, 'orgType'), {t['type']})" if t.get('type') else None)) if v)
    return f"""// Its organisation's Account (one per organisation, whatever the response): the one linked
// to its organisation in the list, else (typed in, "Other") the unlisted one of that name;
// made if there's none. A typed-in organisation later picked from the list: it moves to
// that organisation's Account, or its Account takes the list entry
// (trait account_from_organisation)
$listed = {org} && record\\attribute('COrganisation', {org}, 'code') != 'other';
if (!accountId || {changed([org, other], new=False)}) {{
    $acc = null;
    $orgName = ifThenElse($listed, record\\attribute('COrganisation', {org}, 'name'), {other});
    if ($listed) {{
        $acc = record\\findOne('Account', 'createdAt', 'asc', 'cOrganisationId=', {org});
        if (!$acc && accountId && !record\\attribute('Account', accountId, 'cOrganisationId')) {{
            record\\update('Account', accountId, 'cOrganisationId', {org}, 'name', $orgName);
            $acc = accountId;
        }}
    }} else if ({other}) {{
        $acc = record\\findOne('Account', 'createdAt', 'asc', 'name=', {other}, 'cOrganisationId=', null);
    }}
    if (!$acc && $orgName) {{
        $acc = record\\create('Account', 'name', $orgName, 'cOrganisationId', ifThenElse($listed, {org}, null){extra});
    }}
    if ($acc) {{
        accountId = $acc;
    }}
}}"""


def find_or_make_contact(t, entity):
    acc, email, phone = f"{t.get('account', 'account')}Id", t.get('email', 'emailAddress'), t.get('phone', 'phone')
    name, title, contact = t.get('name', 'name'), t.get('title'), f"{t.get('contact', 'contact')}Id"
    fill = [(phone, 'phoneNumber')] + ([(title, 'title')] if title else [])
    return f"""// Its person: the Contact on its Account with its email, else its phone; made if none (so
// someone named in several reports is one Contact), and the Contact's blank phone and title
// filled (trait find_or_make_contact)
if ({acc} && ({email} || {phone}) && (!{contact} || {changed([acc, email, phone], new=False)})) {{
    $c = null;
    if ({email}) {{
        $c = record\\findOne('Contact', 'createdAt', 'asc', 'accountId=', {acc}, 'emailAddress=', {email});
    }}
    if (!$c && {phone}) {{
        $c = record\\findOne('Contact', 'createdAt', 'asc', 'accountId=', {acc}, 'phoneNumber=', {phone});
    }}
    if (!$c) {{
        $full = string\\trim({name});
        $words = string\\split($full, ' ');
        $last = ifThenElse($full, array\\at($words, array\\length($words) - 1), ifThenElse({email}, {email}, {phone}));
        $c = record\\create('Contact', 'accountId', {acc},
            'firstName', ifThenElse($full, string\\trim(string\\substring($full, 0, string\\length($full) - string\\length($last))), null),
            'lastName', $last,
            'emailAddress', {email}, 'phoneNumber', {phone}{''.join(f", 'title', {title}" for _ in [1] if title)});
    }} else {{
{chr(10).join(f"        if ({v} && !record\\attribute('Contact', $c, {q(a)})) {{{chr(10)}            record\\update('Contact', $c, {q(a)}, {v});{chr(10)}        }}" for v, a in fill)}
    }}
    {contact} = $c;
}}"""


def cascade(children, entity):
    """The parent's side of its children's inherits with `cascade`: (child, link, copy)."""
    out = []
    for child, link, copy in children:
        args = ', '.join(f"{q(f)}, {f}" for f in copy)
        out += [f"// Its {child} records follow: {', '.join(copy)} (trait cascade, {child}'s inherit)",
                f"if (!entity\\isNew() && ({changed(copy, new=False)})) {{",
                f"    $rows = record\\findMany({q(child)}, {ROWS}, 'createdAt', 'asc', {q(link + 'Id=')}, id);",
                "    $i = 0;", "    while ($i < array\\length($rows)) {",
                f"        record\\update({q(child)}, array\\at($rows, $i), {args});", "        $i = $i + 1;", "    }", '}']
    return '\n'.join(out)


RENDER = {'portal_default': portal_default, 'pcodes': pcodes, 'inherit': inherit, 'checks': checks,
          'supersede': supersede, 'teams_up': teams_up, 'cascade': cascade,
          'teams_from_clusters': teams_from_clusters, 'cluster_teams': cluster_teams,
          'account_from_organisation': account_from_organisation, 'find_or_make_contact': find_or_make_contact}


def cascades(traits):
    """By parent entity: the (child, link, copy) of every inherit with `cascade`."""
    out = {}
    for child, t in traits.items():
        for e in t.get('inherit', []):
            if e.get('cascade'):
                if e.get('unless'):
                    raise ValueError(f'{child}: inherit from {e["link"]}: cascade with unless')
                out.setdefault(e['entity'], []).append((child, e['link'], e['copy']))
    return out


def derived(traits):
    """What other entities' traits put in an entity's script, by entity: the cascades (its
    children's inherits) and the cluster teams (on CProject, from teams_from_clusters)."""
    out = {e: {'cascade': c} for e, c in cascades(traits).items()}
    clusters = [(child, None if t['teams_from_clusters'].get('all') else t['teams_from_clusters'].get('clusters', 'clusters'))
                for child, t in traits.items() if 'teams_from_clusters' in t]
    if clusters:
        out.setdefault('CProject', {})['cluster_teams'] = clusters
    return out


def script(entity, blocks, traits, extra=None):
    """An entity's Before Save Custom Script: its traits' snippets (and those other entities'
    traits put in it, derived()) and the packs' blocks."""
    t = {**traits, **(extra or {})}
    text = '\n'.join(blocks)
    before, after = [], []
    for name in BEFORE + AFTER:
        if name not in t:
            continue
        snippet = RENDER[name](t[name], entity)
        marker = f'// trait: {name}\n'
        if marker in text:
            text = text.replace(marker, snippet + '\n', 1)
        else:
            (before if name in BEFORE else after).append(snippet)
    return '\n'.join(x for x in [*before, text, *after] if x)


def check(entity, traits, fields):
    """What a pack says of its traits, against the entity's fields (None: not a pack's
    entity, e.g. EspoCRM's Contact, so not checked)."""
    unknown = set(traits) - set(TRAITS)
    if unknown:
        raise ValueError(f'{entity}: unknown traits {sorted(unknown)} (traits: {", ".join(TRAITS)})')
    if fields is None:
        return
    pins = not isinstance(traits.get('pcodes'), dict) or traits['pcodes'].get('pins', True)
    need = {'pcodes': ['pcode1', 'pcode2', 'pcode3', 'country'] + (['pcodeStatus', 'latitude'] if pins else []),
            'supersede': ['superseded', 'current'], 'checks': ['dataChecks']}
    for name, fs in need.items():
        missing = [f for f in fs if name in traits and f not in fields]
        if missing:
            raise ValueError(f'{entity}: trait {name} needs the fields {missing}')
    if 'checks' in traits:
        options = fields['dataChecks'].get('options', [])
        if set(traits['checks']) != set(options):
            raise ValueError(f'{entity}: checks {sorted(traits["checks"])} are not dataChecks\' options {sorted(options)}')

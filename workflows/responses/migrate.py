"""Responses from before the country's coordination team (PRODUCT-443): each gets its
"Coordination: <country>" team (made if there's none), and its records follow (the trait
teams_down). A rerun finds nothing to do."""


def migrate(espo):
    done = 0
    for r in espo.call('GET', '/CResponse', {'maxSize': 200, 'select': 'id,country,teamsIds', 'where[0][type]': 'isNotNull',
                                             'where[0][attribute]': 'country'})['list']:
        if not (r.get('country') or '').strip():
            continue
        name = 'Coordination: ' + r['country'].strip()
        team = espo.find('Team', 'name', name) or espo.call('POST', '/Team', body={'name': name})
        if team['id'] not in (r.get('teamsIds') or []):
            espo.call('PUT', f'/CResponse/{r["id"]}', body={'teamsIds': [*(r.get('teamsIds') or []), team['id']]})
            done += 1
    if done:
        print(f'responses: {done} response(s) in their country\'s coordination team')

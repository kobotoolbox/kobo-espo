"""The 5W's records from before organisations were Accounts (plans/fivew-organisations-plan.md,
phases 1 and 2): each saved once, so its formula finds or makes its organisation's Account.
Locations take their activity's (their formula takes it only when made or moved). A rerun
finds nothing to do."""


def every(espo, entity, select, *where):
    params = {'maxSize': 200, 'select': select}
    for i, (kind, attr, *value) in enumerate(where):
        params.update({f'where[{i}][type]': kind, f'where[{i}][attribute]': attr})
        if value:
            params[f'where[{i}][value]'] = value[0]
    out, offset = [], 0
    while True:
        page = espo.call('GET', f'/{entity}', {**params, 'offset': offset})['list']
        out += page
        offset += 200
        if len(page) < 200:
            return out


def migrate(espo, rekeyed=None):
    done = {}
    # Registrations: saved, so their formula finds or makes the Account (every registration
    # names an organisation, so none is left for a rerun)
    for r in every(espo, 'CResponder', 'id,name,organisationId,organisationOther', ('isNull', 'accountId')):
        if r.get('organisationId') or r.get('organisationOther'):
            try:
                espo.call('PUT', f'/CResponder/{r["id"]}', body={'name': r['name']})
                done['CResponder (Accounts)'] = done.get('CResponder (Accounts)', 0) + 1
            except Exception as e:  # e.g. refused by its API script: left as it is
                print(f'fivew: CResponder {r["id"]} not migrated ({e})')
    # Activities, then locations: the Account their formula would give them, set directly
    # (its registration's, else its lead organisation's if it has one)
    registration, organisation = {}, {}

    def account_of(act):
        if act.get('responderId'):
            if act['responderId'] not in registration:
                registration[act['responderId']] = espo.call('GET', f'/CResponder/{act["responderId"]}').get('accountId')
            return registration[act['responderId']]
        org = act.get('leadOrganisationId')
        if org and org not in organisation:
            found = every(espo, 'Account', 'id', ('equals', 'cOrganisationId', org))
            organisation[org] = found[0]['id'] if found else None
        return organisation.get(org)
    for entity, parent, select in (('CActivity', None, 'id,responderId,leadOrganisationId'),
                                   ('CActivityLocation', 'activityId', 'id,activityId')):
        for r in every(espo, entity, select, ('isNull', 'accountId')):
            if parent:
                acc = r.get(parent) and espo.call('GET', f'/CActivity/{r[parent]}').get('accountId')
            else:
                acc = account_of(r)
            if acc:
                espo.call('PUT', f'/{entity}/{r["id"]}', body={'accountId': acc})
                done[f'{entity} (Accounts)'] = done.get(f'{entity} (Accounts)', 0) + 1
    # Registrations' focal points (their Contacts, by the form's email) on the organisation's
    # Account, from before people were (PRODUCT-438): their Account's teams follow (formula)
    for r in every(espo, 'CResponder', 'id,contactId,accountId,focalPointPhone', ('isNotNull', 'contactId'), ('isNotNull', 'accountId')):
        c = espo.call('GET', f'/Contact/{r["contactId"]}', {'select': 'accountId,phoneNumber'})
        if not c.get('accountId'):
            espo.call('PUT', f'/Contact/{r["contactId"]}', body={
                'accountId': r['accountId'], **({'phoneNumber': r['focalPointPhone']}
                                                if r.get('focalPointPhone') and not c.get('phoneNumber') else {})})
            done['Contact (Accounts)'] = done.get('Contact (Accounts)', 0) + 1
    # Activities' focal points from before they were Contacts (PRODUCT-439): given their
    # activity's Account, their formula finds or makes their person's Contact
    for r in every(espo, 'CFocalPoint', 'id,activityId,accountId', ('isNull', 'contactId'), ('isNotNull', 'activityId')):
        acc = r.get('accountId') or espo.call('GET', f'/CActivity/{r["activityId"]}').get('accountId')
        if acc:
            espo.call('PUT', f'/CFocalPoint/{r["id"]}', body={'accountId': acc})
            done['CFocalPoint (Contacts)'] = done.get('CFocalPoint (Contacts)', 0) + 1
    # Clusters' partners, from before the organisation portal (PRODUCT-441): the Accounts of
    # the organisations registered in each project's sector; its contacts follow (formula)
    regs = {}
    for p in every(espo, 'CProject', 'id,responseId,cluster,partnersIds', ('isNotNull', 'responseId'), ('isNotNull', 'cluster')):
        if p['responseId'] not in regs:
            regs[p['responseId']] = every(espo, 'CResponder', 'id,accountId,clusters', ('equals', 'responseId', p['responseId']))
        want = sorted({r['accountId'] for r in regs[p['responseId']] if r.get('accountId') and p['cluster'] in (r.get('clusters') or [])})
        if want != sorted(p.get('partnersIds') or []):
            espo.call('PUT', f'/CProject/{p["id"]}', body={'partnersIds': want})
            done['CProject (partners)'] = done.get('CProject (partners)', 0) + 1
    # Locations from before they had their activity's who and what, and their parish's
    # P-code (PRODUCT-442): saved, so their formula copies them
    for r in every(espo, 'CActivityLocation', 'id,name', ('isNotNull', 'activityId'), ('isNull', 'sector')):
        espo.call('PUT', f'/CActivityLocation/{r["id"]}', body={'name': r['name']})
        done['CActivityLocation (who and what)'] = done.get('CActivityLocation (who and what)', 0) + 1
    # Areas re-keyed this run (their codes became the geocoder's, PRODUCT-428): locations
    # saved again, so their formula gives them their parish's new code and names
    if (rekeyed or {}).get('CAdminArea'):
        for r in every(espo, 'CActivityLocation', 'id,name', ('isNotNull', 'communityId')):
            espo.call('PUT', f'/CActivityLocation/{r["id"]}', body={'name': r['name']})
            done['CActivityLocation (areas re-keyed)'] = done.get('CActivityLocation (areas re-keyed)', 0) + 1
    if done:
        print('fivew: migrated ' + ', '.join(f'{n} {e}' for e, n in done.items()))

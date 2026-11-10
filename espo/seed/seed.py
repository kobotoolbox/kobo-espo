#!/usr/bin/env python3
"""
Set up this EspoCRM for the plan's workflows (A: request intake, B: response tasking,
C: sites and lists). Idempotent: run it again after changing anything here.

    python3 -I espo/seed/seed.py [--url https://staging.respond.kobolabs.dev] [--users]

Makes, with the admin API only (no files on the server):
  - entities: Response (CResponse), Cluster project (CProject), Site (CSite), Standard
    (CStandard), their fields, and the links Task -> Response and Project, Site -> Response
    and Project, Project -> Response; a Task's parent can be a Site (or a Case);
  - Task: board columns on its status (Backlog, To do, In progress, Blocked, Done; EspoCRM's
    own Not Started/Started/Completed are relabelled, not replaced, so its "completed" logic
    keeps working), Kanban on, a Task takes its Response's teams;
  - Case: source, category; one team only (API Before Save Script refuses a second);
  - Contact: profileType, availability;
  - teams and roles (staff, triager, partner staff, roster, volunteer, cluster lead, partner
    and viewer), see TEAMS, ROLES;
  - formulas: espo/formula/*.formula, one per entity and script type;
  - settings: assignment notifications for cases and tasks;
  - outgoing email with Resend, when secrets/resend.key is there (a send-only API key):
    the from address, SMTP, the system's group email account, assignment and mention
    emails (see EMAIL).
--users makes the test users (USERS) with generated passwords, kept in
secrets/seed.secrets (gitignored).

The bridge's API users and roles aren't made here: kobo-espo-bridge's setup.py makes them per
template (kobo/templates/*.toml), each with only what its template needs.
"""
import argparse
import json
import os
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from lib import URL, Espo, admin, pw_key, secrets as read_secrets  # noqa: E402

sys.path.insert(0, str(ROOT / 'agents'))
import tools as agent_tools  # noqa: E402  (the code tools an agent may use: its Tools field's options)

TEAMS = ['Internal Kobo', 'Project: Consortium A', 'Project: Consortium B',
         'Response: Test EQ 1', 'Response: Test EQ 2', 'Roster and volunteers', 'Grants review',
         'Cluster: Test EQ 1 ETC', 'Cluster: Test EQ 1 WASH',
         # Workflow F: a country's CSO coordinators ("CSO: " and the country's admin0 name, as
         # the CSO formula finds them), and the CSOs in no country with a team
         'CSO: Kenya', 'CSO: Uganda', 'CSO: Unassigned']

# Workflow E (plans/workflow-e-5w-plan.md): the Hurricane Melissa 5W form's lists, with its
# own codes (ref/, extracted to espo/seed/data/fivew-melissa.json), so its submissions and
# its choice lists fit EspoCRM as they are
FIVEW = json.loads((ROOT / 'espo' / 'seed' / 'data' / 'fivew-melissa.json').read_text())


def choices(name):
    return {c['code']: c['label'] for c in FIVEW[name]}


# A project's sector (its cluster), and the sectors an organisation works in
SECTORS = choices('sectors')
# Codes before the Melissa form's: the seed moves projects and organisations to these
OLD_CLUSTERS = {'etc': 'EMERGENCY_TELECOMS', 'wash': 'WASH', 'shelter': 'SHELTER', 'health': 'HEALTH',
                'food_security': 'FOOD_SECURITY', 'early_recovery': 'EARLY_RECOVERY', 'education': 'EDUCATION',
                'nutrition': 'NUTRITION', 'protection': 'PROTECTION', 'cccm': 'other_sector',
                'logistics': 'other_sector', 'other': 'other_sector'}
# People by group (displaced, hosting, non-displaced, other), each targeted and reached:
# the form's question names and the fields they go to
GROUPS = {'idp': ('idp', 'idp_household'), 'hosting': ('hosting', 'people_hosting_household'),
          'ndp': ('ndp', 'non_displaced_household'), 'other': ('other', 'other_population_household')}


# Data checks (formulas): flags on what looks wrong in a report, for the IM team to follow
# up. Flags, not refusals: a report from the field is kept, and fixed or explained
ACTIVITY_CHECKS = {'completed_nobody_reached': 'Completed, nobody reached', 'no_communities': 'No community given',
                   'completed_ends_later': 'Completed, but ends in the future'}
LOCATION_CHECKS = {'reached_over_targeted': 'More reached than targeted',
                   'groups_over_total': "The groups add up to more than the total reached",
                   'group_parts_dont_add_up': "A group's women, men and children don't add up to its people"}


# Workflow F (plans/cso-mapping-plan.md): the CSO mapping's lists, with codes, as its forms
# have them (kobo/forms/cso.py reads the same file)
CSO_LISTS = json.loads((ROOT / 'espo' / 'seed' / 'data' / 'cso-lists.json').read_text())
UPDATE_CHECKS = {'key_missing': 'No key: check it is the CSO\'s', 'key_wrong': "Wrong key: not the CSO's link",
                 'outside': 'The pin is outside the country', 'not_in_presence': "Not in the CSO's places",
                 'role_not_in_profile': "A role not in the CSO's profile"}


def cso_options(name):
    v = CSO_LISTS[name]
    return {c['code']: c['label'] for c in (v['choices'] if isinstance(v, dict) else v)}


def cso_enum(name, label=None, many=False, **kw):
    opts = cso_options(name)
    return {'type': 'multiEnum' if many else 'enum', 'options': ([] if many else ['']) + list(opts),
            'translatedOptions': opts, **({'label': label} if label else {}), **kw}


def cso_place_fields():
    """Where a CSO's place or update is: its area and P-codes, or a pin to P-code."""
    return {
        'country': cso_enum('countries', 'Country'),
        'pcode1': {'type': 'varchar', 'label': 'P-code (admin1)', 'maxLength': 30},
        'pcode2': {'type': 'varchar', 'label': 'P-code (admin2)', 'maxLength': 30},
        'pcode3': {'type': 'varchar', 'label': 'P-code (admin3)', 'maxLength': 30},
        'latitude': {'type': 'float', 'label': 'Latitude'},
        'longitude': {'type': 'float', 'label': 'Longitude'},
        'pcodeStatus': {'type': 'enum', 'label': 'P-coding', 'options': ['', 'given', 'pending', 'done', 'outside'],
                        'translatedOptions': {'': '', 'given': 'Area given', 'pending': 'Pin, to P-code',
                                              'done': 'P-coded from the pin', 'outside': 'Pin outside the boundaries'},
                        'style': {'outside': 'danger', 'pending': 'warning'}},
        # What the dashboard's feeds read of the CSO (a feed reads one entity): its formula's.
        # Its name is the link's own (csoName)
        'csoType': cso_enum('cso_types', 'CSO type', readOnly=True),
        'listed': {'type': 'bool', 'label': 'Listed', 'readOnly': True,
                   'tooltipText': 'In the directory and the matching (the CSO did not say no to sharing)'},
    }


def enum(name, label=None, blank=True, **kw):
    opts = choices(name)
    return {'type': 'enum', 'options': ([''] if blank else []) + list(opts), 'translatedOptions': opts,
            **({'label': label} if label else {}), **kw}


def group_fields():
    out = {}
    for g in GROUPS:
        for when in ('Targeted', 'Reached'):
            for who in ('People', 'Women', 'Men', 'Children', 'Households'):
                out[f'{g}{who}{when}'] = {'type': 'int', 'min': 0,
                                          'label': f'{choices("population_groups")[g][:40]}: {who.lower()} {when.lower()}'}
    return out

ENTITIES = {
    'Response': {'labelPlural': 'Responses', 'iconClass': 'fas fa-house-damage', 'fields': {
        'status': {'type': 'enum', 'options': ['Planning', 'Active', 'Closed'], 'default': 'Planning',
                   'style': {'Active': 'success', 'Closed': 'info'}},
        'emergencyType': {'type': 'enum', 'label': 'Emergency type',
                          'options': ['', 'Earthquake', 'Flood', 'Cyclone', 'Drought', 'Conflict', 'Epidemic', 'Other']},
        'country': {'type': 'varchar'},
        'startDate': {'type': 'date', 'label': 'Start date'},
        'endDate': {'type': 'date', 'label': 'End date'},
    }},
    # A cluster's project in a response (e.g. Emergency Telecommunications in Hurricane
    # Melissa): in its own team and its response's, so the cluster's people see its sites and
    # tasks, and the response's coordinators see every project's
    'Project': {'label': 'Cluster project', 'labelPlural': 'Cluster projects', 'iconClass': 'fas fa-layer-group', 'fields': {
        'cluster': {'type': 'enum', 'label': 'Sector', 'options': [''] + list(SECTORS), 'translatedOptions': SECTORS},
        'status': {'type': 'enum', 'options': ['Planning', 'Active', 'Closed'], 'default': 'Planning',
                   'style': {'Active': 'success', 'Closed': 'info'}},
        'startDate': {'type': 'date', 'label': 'Start date'},
        'endDate': {'type': 'date', 'label': 'End date'},
    }},
    'Site': {'labelPlural': 'Sites', 'iconClass': 'fas fa-map-marker-alt', 'fields': {
        'siteCode': {'type': 'varchar', 'label': 'Site code', 'required': True},
        # Values as the Kobo forms' choice names, labels as people read them
        'siteType': {'type': 'enum', 'label': 'Site type',
                     'options': ['', 'water_point', 'solar', 'health_post', 'shelter', 'other'],
                     'translatedOptions': {'water_point': 'Water point', 'solar': 'Solar installation',
                                           'health_post': 'Health post', 'shelter': 'Shelter', 'other': 'Other'}},
        'status': {'type': 'enum', 'options': ['planned', 'operational', 'needs_repair', 'decommissioned'],
                   'translatedOptions': {'planned': 'Planned', 'operational': 'Operational',
                                         'needs_repair': 'Needs repair', 'decommissioned': 'Decommissioned'},
                   'default': 'planned', 'style': {'operational': 'success', 'needs_repair': 'danger'}},
        'region': {'type': 'varchar'},
        'latitude': {'type': 'float', 'decimalPlaces': 6},
        'longitude': {'type': 'float', 'decimalPlaces': 6},
        'installedAt': {'type': 'date', 'label': 'Installed'},
        'equipment': {'type': 'text'},
        'lastVisit': {'type': 'date', 'label': 'Last visit'},
        'photos': {'type': 'attachmentMultiple'},  # from the registration form (kobo-espo-bridge media)
    }},
    # Workflow E: the organisations in the response, as the 5W form lists them (its ORG_
    # codes), read by everyone. "other" is the form's own: one not in the list yet
    'Organisation': {'label': 'Organisation', 'labelPlural': 'Organisations', 'iconClass': 'fas fa-building',
                     'stream': False, 'fields': {
        'code': {'type': 'varchar', 'required': True, 'maxLength': 60, 'tooltipText': "The 5W form's code, e.g. ORG_ADRA"},
        'orgType': enum('org_types', 'Type'),
    }},
    # Workflow E: an organisation registered as responding in a response, for the sectors it
    # works in: in the teams of the response and of its projects in those sectors (formula)
    'Responder': {'label': 'Responding organisation', 'labelPlural': 'Responding organisations',
                  'iconClass': 'fas fa-hands-helping', 'fields': {
        'acronym': {'type': 'varchar', 'maxLength': 30},
        'orgType': enum('org_types', 'Type'),
        'organisationOther': {'type': 'varchar', 'label': 'Organisation (not in the list)'},
        'clusters': {'type': 'multiEnum', 'label': 'Sectors', 'options': list(SECTORS), 'translatedOptions': SECTORS},
        'status': {'type': 'enum', 'options': ['registered', 'active', 'inactive'], 'default': 'registered',
                   'translatedOptions': {'registered': 'Registered', 'active': 'Reporting', 'inactive': 'Inactive'},
                   'style': {'active': 'success', 'inactive': 'info'}},
        'focalPoint': {'type': 'varchar', 'label': 'Focal point'},
        'focalPointPhone': {'type': 'varchar', 'label': 'Focal point phone', 'maxLength': 40},
        'registrationKey': {'type': 'varchar', 'label': 'Registration key',
                            'tooltipText': 'Response and organisation: registering again updates the same record'},
        'lastReport': {'type': 'date', 'label': 'Last report'},
    }},
    # Workflow E: one activity of an organisation (a 5W form submission): who, what, when,
    # with what. Where and for how many are its locations, one per community
    'Activity': {'label': 'Activity', 'labelPlural': 'Activities', 'iconClass': 'fas fa-clipboard-check', 'fields': {
        'leadOrganisationOther': {'type': 'varchar', 'label': 'Lead organisation (not in the list)'},
        'implementingOrganisationOther': {'type': 'varchar', 'label': 'Implementing organisation (not in the list)'},
        'sector': enum('sectors'),
        'sectorOther': {'type': 'varchar', 'label': 'Sector (other)'},
        'activityType': enum('activity_types', 'Activity type'),
        'activityTypeOther': {'type': 'varchar', 'label': 'Activity type (other)'},
        'title': {'type': 'varchar', 'label': 'Activity title'},
        'status': enum('activity_status', blank=False, default='IN_PROGRESS', style={'COMPLETED': 'success'}),
        'comments': {'type': 'text', 'label': 'Comments / description'},
        'resourceUrl': {'type': 'url', 'label': 'Resources (link)'},
        'resourceType': enum('resource_types', 'Resource type'),
        'resourceTypeOther': {'type': 'varchar', 'label': 'Resource type (other)'},
        'resourceUnit': enum('resource_units', 'Unit'),
        'resourceUnitOther': {'type': 'varchar', 'label': 'Unit (other)'},
        'startDate': {'type': 'date', 'label': 'Start date'},
        'endDate': {'type': 'date', 'label': 'End date'},
        'reportDate': {'type': 'date', 'label': 'Reported on'},
        # Its locations' totals (their formula)
        'communities': {'type': 'int', 'label': 'Communities'},
        'quantity': {'type': 'float', 'label': 'Quantity (all communities)'},
        'budget': {'type': 'float', 'label': 'Budget (all communities)'},
        'peopleTargeted': {'type': 'int', 'label': 'People targeted'},
        'peopleReached': {'type': 'int', 'label': 'People reached'},
        'dataChecks': {'type': 'multiEnum', 'label': 'Data checks', 'options': list(ACTIVITY_CHECKS),
                       'translatedOptions': ACTIVITY_CHECKS, 'tooltipText': 'What looks wrong (formula); fix it or explain in a note'},
    }},
    # Workflow E: where an activity happened and for how many: a row of the form's
    # FIGURES_COMMUNITY repeat (the bridge's [[repeat]])
    'ActivityLocation': {'label': 'Activity location', 'labelPlural': 'Activity locations',
                         'iconClass': 'fas fa-map-pin', 'stream': False, 'fields': {
        'locationType': enum('location_types', 'Location type'),
        'locationTypeOther': {'type': 'varchar', 'label': 'Location type (other)'},
        'locationComments': {'type': 'text', 'label': 'Address or comments'},
        'quantity': {'type': 'float'},
        'budget': {'type': 'float', 'label': 'Budget / value'},
        'populationTargeted': {'type': 'int', 'label': 'People targeted', 'min': 0},
        'populationReached': {'type': 'int', 'label': 'People reached', 'min': 0},
        'populationGroups': {'type': 'multiEnum', 'label': 'Groups of people', 'options': list(choices('population_groups')),
                             'translatedOptions': choices('population_groups')},
        'populationGroupsOther': {'type': 'varchar', 'label': 'Groups (other)'},
        'dataChecks': {'type': 'multiEnum', 'label': 'Data checks', 'options': list(LOCATION_CHECKS),
                       'translatedOptions': LOCATION_CHECKS, 'tooltipText': 'What looks wrong (formula); fix it or explain in a note'},
        **group_fields(),
    }},
    # Workflow E: an activity's focal points (the form's FOCAL_POINTS repeat)
    'FocalPoint': {'label': 'Focal point', 'labelPlural': 'Focal points', 'iconClass': 'fas fa-id-badge',
                   'stream': False, 'fields': {
        'emailAddress': {'type': 'varchar', 'label': 'Email', 'maxLength': 150},
        'phone': {'type': 'varchar', 'maxLength': 40},
        'jobTitle': {'type': 'varchar', 'label': 'Job title'},
        # Workflow F: a CSO's focal point is current until the CSO sends its profile again
        'current': {'type': 'bool', 'label': 'Current', 'default': True},
    }},
    # Workflow E: the country's administrative areas (COD-AB P-codes), read by everyone
    'AdminArea': {'label': 'Admin area', 'labelPlural': 'Admin areas', 'iconClass': 'fas fa-map', 'stream': False, 'fields': {
        'pcode': {'type': 'varchar', 'label': 'P-code', 'required': True, 'maxLength': 30},
        'level': {'type': 'enum', 'options': ['admin0', 'admin1', 'admin2', 'admin3', 'admin4'], 'default': 'admin1'},
        'parentPcode': {'type': 'varchar', 'label': 'Parent P-code', 'maxLength': 30},
        'country': {'type': 'varchar', 'label': 'Country (ISO3)', 'maxLength': 3},
    }},
    # Workflow F: a civil society organisation's profile (the CSO profile form). Its own
    # entity, not COrganisation (which everyone reads): a CSO that said no to sharing is
    # seen by its countries' coordinators only (teams by country, formula)
    'Cso': {'label': 'CSO', 'labelPlural': 'CSOs', 'iconClass': 'fas fa-people-carry', 'fields': {
        'acronym': {'type': 'varchar', 'maxLength': 40},
        'csoType': cso_enum('cso_types', 'Type'),
        'csoTypeOther': {'type': 'varchar', 'label': 'Type (other)'},
        'identities': cso_enum('identities', 'Also describes it', many=True),
        'countryRegistered': cso_enum('countries', 'Registered in'),
        'otherCountries': cso_enum('countries', 'Other countries', many=True),
        'countries': cso_enum('countries', 'Countries', many=True, readOnly=True,
                              tooltipText="Where it's registered, its places' countries and the others it named (formula): its teams"),
        'levels': cso_enum('levels', 'Levels', many=True),
        'sharing': cso_enum('sharing', 'Sharing', tooltipText='May its profile and contacts be shared with other CSOs and partners?'),
        'settings': cso_enum('settings', 'Settings it reaches', many=True),
        'settingsOther': {'type': 'varchar', 'label': 'Settings (other)'},
        'populations': cso_enum('populations', 'Populations', many=True),
        'populationsOther': {'type': 'varchar', 'label': 'Populations (other)'},
        'stages': cso_enum('stages', 'Stages', many=True),
        'roles': cso_enum('roles', 'Roles', many=True),
        'rolesOther': {'type': 'varchar', 'label': 'Roles (other)'},
        'rolesCholera': cso_enum('roles_cholera', 'Roles (cholera)', many=True),
        'rolesCholeraOther': {'type': 'varchar', 'label': 'Roles, cholera (other)'},
        'hazards': cso_enum('hazards', 'Hazards', many=True),
        'hazardsOther': {'type': 'varchar', 'label': 'Hazards (other)'},
        'rolesWithSupport': cso_enum('roles', 'Roles with support', many=True),
        'rolesWithSupportOther': {'type': 'varchar', 'label': 'Roles with support (other)'},
        'rolesWithSupportCholera': cso_enum('roles_cholera', 'Roles with support (cholera)', many=True),
        'mechanisms': cso_enum('mechanisms', 'Coordination mechanisms', many=True),
        'mechanismsOther': {'type': 'varchar', 'label': 'Mechanisms (other)'},
        'offers': cso_enum('exchange', 'Offers', many=True),
        'offersOther': {'type': 'varchar', 'label': 'Offers (other)'},
        'seeks': cso_enum('exchange', 'Seeks', many=True),
        'seeksOther': {'type': 'varchar', 'label': 'Seeks (other)'},
        'connectVia': cso_enum('connect_via', 'Connect via', many=True),
        'connectViaOther': {'type': 'varchar', 'label': 'Connect via (other)'},
        'listed': {'type': 'bool', 'label': 'Listed', 'readOnly': True,
                   'tooltipText': 'In the directory and the matching: it did not say no to sharing (formula)'},
        'sharedContact': {'type': 'text', 'label': 'Shared contact', 'readOnly': True,
                          'tooltipText': "Its focal points' contacts, only if it said yes to sharing them (formula): what the directory shows"},
        'lastProfile': {'type': 'date', 'label': 'Profile sent', 'readOnly': True},
        'updateKey': {'type': 'varchar', 'label': 'Key', 'maxLength': 16, 'readOnly': True,
                      'tooltipText': "In the links it is emailed: a submission without it doesn't change this CSO or count as its update"},
        'keyGiven': {'type': 'varchar', 'label': 'Key given', 'maxLength': 40,
                     'tooltipText': 'The key a submission came with: checked, never kept'},
        'verified': {'type': 'bool', 'label': 'Verified by WHO'},
    }},
    # Workflow F: a place where a CSO works (a row of the profile's PRESENCE repeat)
    'Presence': {'label': 'CSO place', 'labelPlural': 'CSO places', 'iconClass': 'fas fa-map-marker-alt',
                 'stream': False, 'fields': {
        **cso_place_fields(),
        'current': {'type': 'bool', 'label': 'Current', 'default': True,
                    'tooltipText': "From the CSO's latest profile (formula)"},
        'settings': cso_enum('settings', 'Settings it reaches', many=True, readOnly=True),
        'populations': cso_enum('populations', 'Populations', many=True, readOnly=True),
        'roles': cso_enum('roles', 'Roles', many=True, readOnly=True),
    }},
    # Workflow F: what a CSO is doing in one place now (the CSO update form)
    'CsoUpdate': {'label': 'CSO update', 'labelPlural': 'CSO updates', 'iconClass': 'fas fa-bullhorn', 'fields': {
        **cso_place_fields(),
        'locality': {'type': 'varchar', 'label': 'Locality'},
        'roles': cso_enum('roles', 'Roles', many=True),
        'rolesOther': {'type': 'varchar', 'label': 'Roles (other)'},
        'rolesCholera': cso_enum('roles_cholera', 'Roles (cholera)', many=True),
        'rolesCholeraOther': {'type': 'varchar', 'label': 'Roles, cholera (other)'},
        'status': cso_enum('update_status', 'Status', style={'active': 'success', 'ready': 'primary', 'suspended': 'warning'}),
        'populations': cso_enum('populations', 'Populations', many=True),
        'populationsOther': {'type': 'varchar', 'label': 'Populations (other)'},
        'facility': {'type': 'varchar', 'label': 'Facility'},
        'needs': cso_enum('exchange', 'Needs', many=True),
        'needsOther': {'type': 'varchar', 'label': 'Needs (other)'},
        'needsNote': {'type': 'text', 'label': 'About the need'},
        'keyGiven': {'type': 'varchar', 'label': 'Key given', 'maxLength': 40,
                     'tooltipText': 'The key the submission came with: checked, never kept'},
        'keyCheck': {'type': 'enum', 'label': 'Key', 'options': ['', 'ok', 'missing', 'wrong', 'confirmed'],
                     'translatedOptions': {'': '', 'ok': "The CSO's", 'missing': 'No key', 'wrong': 'Wrong key',
                                           'confirmed': 'Confirmed by a coordinator'},
                     'style': {'wrong': 'danger', 'missing': 'warning'},
                     'tooltipText': 'Set "Confirmed" once you know the update is the CSO\'s: it then counts'},
        'superseded': {'type': 'bool', 'label': 'Superseded', 'readOnly': True,
                       'tooltipText': 'A newer update of the CSO in this place counts instead (formula)'},
        'current': {'type': 'bool', 'label': 'Counts', 'readOnly': True,
                    'tooltipText': "The CSO's (its key, or confirmed) and not superseded: what the maps read"},
        'dataChecks': {'type': 'multiEnum', 'label': 'Data checks', 'options': list(UPDATE_CHECKS),
                       'translatedOptions': UPDATE_CHECKS, 'tooltipText': 'What looks wrong (formula); fix it or explain in a note'},
    }},
    'Standard': {'labelPlural': 'Standards', 'iconClass': 'fas fa-book', 'fields': {
        'code': {'type': 'varchar', 'required': True},
        'category': {'type': 'enum', 'options': ['', 'WASH', 'Shelter', 'Health', 'Energy', 'Protection']},
        'requirement': {'type': 'text'},
        'source': {'type': 'varchar'},
    }},
    # Agents (plans/espo-agents-plan.md): set up here, run by agents/runner.py
    'Agent': {'labelPlural': 'Agents', 'iconClass': 'fas fa-robot', 'stream': False, 'fields': {
        'mode': {'type': 'enum', 'options': ['off', 'dry_run', 'active'], 'default': 'off',
                 'translatedOptions': {'off': 'Off', 'dry_run': 'Dry run', 'active': 'Active'},
                 'style': {'active': 'success', 'dry_run': 'warning'}, 'audited': True},
        'runner': {'type': 'enum', 'options': ['droplet', 'tests'], 'default': 'droplet',
                   'tooltipText': 'Which runner runs it: the one on the server, or the tests.'},
        'entity': {'type': 'enum', 'label': 'Works on', 'options': ['CApplication', 'CSite', 'Case', 'Task', 'CResponder', 'CActivity',
                                                                     'CCso', 'CPresence', 'CCsoUpdate'],
                   'translatedOptions': {'CApplication': 'Application', 'CSite': 'Site', 'Case': 'Case', 'Task': 'Task',
                                         'CResponder': 'Responding organisation', 'CActivity': 'Activity',
                                         'CCso': 'CSO', 'CPresence': 'CSO place', 'CCsoUpdate': 'CSO update'}},
        'trigger': {'type': 'enum', 'options': ['stage', 'change', 'schedule'],
                    'translatedOptions': {'stage': 'Records in a stage', 'change': 'When a field changes',
                                          'schedule': 'On a schedule'}},
        'triggerStage': {'type': 'varchar', 'label': 'Stage'},
        'watchField': {'type': 'varchar', 'label': 'Watched field'},
        'scheduleEvery': {'type': 'enum', 'label': 'Repeats', 'options': ['', 'hour', 'day', 'week'],
                          'translatedOptions': {'': '', 'hour': 'Every hour', 'day': 'Every day', 'week': 'Every week'}},
        'scheduleAt': {'type': 'varchar', 'label': 'At (UTC)', 'maxLength': 5,
                       'tooltipText': 'HH:MM, e.g. 06:00. Every hour: only the minutes count.'},
        'scheduleWeekday': {'type': 'enum', 'label': 'On (every week)', 'options': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
                            'default': 'Mon'},
        'idleField': {'type': 'varchar', 'label': 'Only if this date is older than',
                      'tooltipText': 'A date field, e.g. lastVisit or modifiedAt; with the days next to it.'},
        'idleDays': {'type': 'int', 'label': 'days', 'min': 1},
        'filterField': {'type': 'varchar', 'label': 'Only where field'},
        'filterValue': {'type': 'varchar', 'label': 'equals'},
        'readFields': {'type': 'array', 'label': 'Reads', 'audited': True},
        'readNotes': {'type': 'bool', 'label': 'Reads the latest note'},
        'readAttachments': {'type': 'varchar', 'label': 'Reads the files in field'},
        'tools': {'type': 'multiEnum', 'options': [*agent_tools.TOOLS, *sorted(agent_tools.SERVER_TOOLS)], 'audited': True},
        'instructions': {'type': 'text', 'audited': True},
        'outputFields': {'type': 'array', 'label': 'Fills in', 'audited': True},
        'model': {'type': 'enum', 'options': ['', 'claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5'],
                  'translatedOptions': {'': 'None (rules only)'}, 'default': 'claude-opus-5-5', 'audited': True},
        'maxAttempts': {'type': 'int', 'label': 'Max attempts', 'default': 3, 'min': 1, 'max': 10},
        'budgetPerRun': {'type': 'float', 'label': 'Budget per run (USD)', 'default': 0.5},
        'onFailure': {'type': 'varchar', 'label': 'Route on failure'},
        'version': {'type': 'int', 'default': 1, 'readOnly': True},
        'activeSince': {'type': 'datetime', 'label': 'Working since', 'readOnly': True},
    }},
    'AgentRoute': {'labelPlural': 'Agent routes', 'iconClass': 'fas fa-route', 'stream': False, 'fields': {
        'order': {'type': 'int', 'default': 10},
        'ruleField': {'type': 'varchar', 'label': 'Rule: field', 'tooltipText': 'A field, a tool result, or "text" (the read fields and note)'},
        'ruleOp': {'type': 'enum', 'label': 'Rule: test', 'options': ['', 'equals', 'in', 'contains', 'matches']},
        'ruleValue': {'type': 'varchar', 'label': 'Rule: value', 'maxLength': 500},
        'ruleWhen': {'type': 'enum', 'label': 'Rule applies', 'options': ['before', 'after'],
                     'translatedOptions': {'before': 'Before the model (skips it)', 'after': 'After the model (overrides it)'}},
        'moveToStage': {'type': 'varchar', 'label': 'Move to stage'},
        'clearAssignee': {'type': 'bool', 'label': 'Unassign'},
        'createTask': {'type': 'bool', 'label': 'Create a task'},
        'taskName': {'type': 'varchar', 'label': 'Task name', 'tooltipText': 'e.g. Urgent: {name}'},
        'taskStatus': {'type': 'varchar', 'label': 'Task status', 'default': 'Backlog'},
        'taskPriority': {'type': 'enum', 'label': 'Task priority', 'options': ['Low', 'Normal', 'High', 'Urgent'], 'default': 'Normal'},
        'taskAssignFrom': {'type': 'varchar', 'label': 'Task assignee from',
                           'tooltipText': 'A user link on the record or its response, e.g. response.lead'},
        'setFields': {'type': 'text', 'label': 'Set fields (JSON)'},
        'fixedNote': {'type': 'text', 'label': 'Fixed note', 'tooltipText': 'Posted instead of the model\'s words'},
        'notify': {'type': 'bool', 'label': 'Mention the assignee'},
        'onlyOneOpen': {'type': 'bool', 'label': 'Not while one is open',
                        'tooltipText': "No new task while the record's last one from here is still open"},
    }},
    'AgentRun': {'labelPlural': 'Agent runs', 'iconClass': 'fas fa-history', 'stream': False, 'fields': {
        'status': {'type': 'enum', 'options': ['running', 'done', 'dry_run', 'failed'], 'default': 'running',
                   'style': {'done': 'success', 'failed': 'danger', 'dry_run': 'warning'}},
        'recordType': {'type': 'varchar'},
        'recordId': {'type': 'varchar'},
        'recordName': {'type': 'varchar'},
        'triggerKey': {'type': 'varchar', 'maxLength': 255},
        'agentVersion': {'type': 'int'},
        'model': {'type': 'varchar'},
        'promptHash': {'type': 'varchar'},
        'route': {'type': 'varchar'},
        'routeBy': {'type': 'enum', 'options': ['', 'rule_before', 'model', 'rule_after', 'failure']},
        'reason': {'type': 'text'},
        'output': {'type': 'text'},
        'error': {'type': 'text'},
        'attempts': {'type': 'int', 'default': 0},
        'inputTokens': {'type': 'int'},
        'outputTokens': {'type': 'int'},
        'cost': {'type': 'float', 'decimalPlaces': 4},
        'durationS': {'type': 'float', 'label': 'Duration (s)'},
    }},
    # Workflow D: an organisation's application for support, through due diligence
    'Application': {'labelPlural': 'Applications', 'iconClass': 'fas fa-file-signature', 'statusField': 'stage', 'fields': {
        'stage': {'type': 'enum', 'options': ['Submitted', 'Screening', 'Research', 'Review', 'Needs info', 'Decision',
                                              'Approved', 'Rejected'], 'default': 'Submitted',
                  'style': {'Review': 'primary', 'Needs info': 'warning', 'Approved': 'success', 'Rejected': 'danger'}},
        'country': {'type': 'varchar'},
        'registrationNumber': {'type': 'varchar', 'label': 'Registration number'},
        'website': {'type': 'url'},
        'amountRequested': {'type': 'float', 'label': 'Amount requested (USD)'},
        'purpose': {'type': 'text'},
        'leadership': {'type': 'text', 'tooltipText': 'Names of the organisation\'s leaders, one per line'},
        'documents': {'type': 'attachmentMultiple'},
        'noticeVersion': {'type': 'varchar', 'label': 'Notice version'},
        'ddSanctions': {'type': 'enum', 'label': 'Sanctions', 'options': ['', 'clear', 'possible_match', 'match'],
                        'translatedOptions': {'clear': 'Clear', 'possible_match': 'Possible match', 'match': 'Match'},
                        'style': {'clear': 'success', 'possible_match': 'warning', 'match': 'danger'}},
        'ddSanctionsDetail': {'type': 'text', 'label': 'Sanctions detail'},
        'ddRegistry': {'type': 'enum', 'label': 'Registry', 'options': ['', 'found', 'not_found', 'not_checked']},
        'ddRisk': {'type': 'enum', 'label': 'Risk', 'options': ['', 'low', 'medium', 'high', 'unknown'],
                   'style': {'low': 'success', 'medium': 'warning', 'high': 'danger'}},
        'ddFlags': {'type': 'multiEnum', 'label': 'Flags',
                    'options': ['name_mismatch', 'no_web_presence', 'doc_unreadable', 'new_org', 'adverse_media',
                                'inconsistent_figures', 'instructions_in_application']},
        'ddSummary': {'type': 'text', 'label': 'Due diligence summary'},
    }},
}
# Short codes (espo/formula/_code.formula), as Ponto's: what people say and Kobo lists use as
# choice names (a list's name = "code", a template's link lookup = "code"). Sites have their
# site code, standards their code, admin areas their P-code, cases EspoCRM's number
CODES = {'CResponse': 'RSP', 'CProject': 'PRJ', 'CResponder': 'REG', 'CActivity': 'ACT', 'Task': 'TSK',
         'CApplication': 'APP', 'CCso': 'CSO'}
CODE_FIELD = {'type': 'varchar', 'label': 'Code', 'maxLength': 12, 'readOnly': True,
              'tooltipText': 'Given by EspoCRM, e.g. PRJ-7K3Q: to name this record, and in Kobo lists'}


def code_field(entity):
    return 'code' if entity.startswith('C') and entity not in ('Case', 'Contact') else 'cCode'


# What the 5W's first draft had that the Melissa form doesn't (removed by the seed): an
# activity's location and people are its locations' now
OBSOLETE_FIELDS = {'CActivity': ['girls', 'boys', 'women', 'men', 'elderlyWomen', 'elderlyMen', 'households', 'unit']}
OBSOLETE_LINKS = [('CActivity', 'adminArea'), ('CActivity', 'site')]

# The entities agents work on: their API Before Save Script starts with _agent-guard.formula
AGENT_GUARDED = ['CApplication', 'CSite', 'Task', 'CResponder']
# (entity, link, foreign entity, foreign link, type). The link on Task, EspoCRM's own
# entity, gets a "c": Task.cResponse (cResponseId); on Site, a custom one, it's Site.response
LINKS = [('CResponse', 'tasks', 'Task', 'response', 'oneToMany'),
         ('CResponse', 'sites', 'CSite', 'response', 'oneToMany'),
         ('CStandard', 'sites', 'CSite', 'standard', 'oneToMany'),  # the standard a site follows
         ('CResponse', 'projects', 'CProject', 'response', 'oneToMany'),
         ('CProject', 'sites', 'CSite', 'project', 'oneToMany'),
         ('CProject', 'tasks', 'Task', 'project', 'oneToMany'),  # Task.cProject
         ('CProject', 'lead', 'User', 'leadOfProjects', 'manyToOne'),
         ('CResponse', 'responders', 'CResponder', 'response', 'oneToMany'),
         ('CResponder', 'account', 'Account', 'responderProfiles', 'manyToOne'),
         ('CResponder', 'contact', 'Contact', 'responderProfiles', 'manyToOne'),  # the focal point
         ('CResponder', 'activities', 'CActivity', 'responder', 'oneToMany'),
         ('CProject', 'activities', 'CActivity', 'project', 'oneToMany'),
         ('CResponse', 'activities', 'CActivity', 'response', 'oneToMany'),
         ('CResponder', 'organisation', 'COrganisation', 'registrations', 'manyToOne'),
         ('CActivity', 'leadOrganisation', 'COrganisation', 'activitiesLed', 'manyToOne'),
         ('CActivity', 'implementingOrganisation', 'COrganisation', 'activitiesImplemented', 'manyToOne'),
         ('CActivity', 'locations', 'CActivityLocation', 'activity', 'oneToMany'),
         ('CActivity', 'focalPoints', 'CFocalPoint', 'activity', 'oneToMany'),
         ('CActivityLocation', 'parish', 'CAdminArea', 'locationsInParish', 'manyToOne'),
         ('CActivityLocation', 'community', 'CAdminArea', 'locationsInCommunity', 'manyToOne'),
         ('CActivityLocation', 'site', 'CSite', 'activityLocations', 'manyToOne'),
         ('CActivityLocation', 'project', 'CProject', 'activityLocations', 'manyToOne'),
         ('CActivityLocation', 'response', 'CResponse', 'activityLocations', 'manyToOne'),
         ('CResponse', 'lead', 'User', 'leadOfResponses', 'manyToOne'),
         ('CAgent', 'routes', 'CAgentRoute', 'agent', 'oneToMany'),
         ('CAgent', 'user', 'User', 'agentProfiles', 'manyToOne'),  # its API user (agents/sync.py)
         ('CAgentRoute', 'assignUser', 'User', 'agentRoutes', 'manyToOne'),
         ('CAgentRoute', 'assignAgent', 'CAgent', 'routedHere', 'manyToOne'),  # hand over to another agent
         ('CAgent', 'runs', 'CAgentRun', 'agent', 'oneToMany'),
         ('CApplication', 'account', 'Account', 'applications', 'manyToOne'),
         ('CApplication', 'contact', 'Contact', 'applications', 'manyToOne'),
         # Workflow F
         ('CCso', 'presence', 'CPresence', 'cso', 'oneToMany'),
         ('CCso', 'updates', 'CCsoUpdate', 'cso', 'oneToMany'),
         ('CCso', 'focalPoints', 'CFocalPoint', 'cso', 'oneToMany'),
         ('CCso', 'organisation', 'COrganisation', 'csoProfiles', 'manyToOne'),  # when it's in the 5W's list too
         ('CPresence', 'adminArea', 'CAdminArea', 'csoPlaces', 'manyToOne'),
         ('CCsoUpdate', 'adminArea', 'CAdminArea', 'csoUpdates', 'manyToOne'),
         ('CCsoUpdate', 'response', 'CResponse', 'csoUpdates', 'manyToOne')]

FIELDS = {
    'Case': {
        # cCategory comes from the support form (kobo/templates/support-request.toml)
        'source': {'type': 'enum', 'options': ['Kobo form', 'Email', 'Manual'], 'default': 'Manual'},
    },
    'Contact': {
        'profileType': {'type': 'enum', 'label': 'Profile type',
                        'options': ['', 'Roster', 'Volunteer', 'Partner contact']},
        'availability': {'type': 'text'},
        # cSkills, cLanguages come from the volunteer form (kobo/templates/volunteer.toml)
    },
}

# Board columns. EspoCRM's own statuses stay (its "completed" date and "actual" filters use
# them), relabelled; Backlog and Blocked are added
TASK_STATUS = ['Backlog', 'Not Started', 'Started', 'Blocked', 'Completed', 'Canceled', 'Deferred']
TASK_LABELS = {'Backlog': 'Backlog', 'Not Started': 'To do', 'Started': 'In progress',
               'Blocked': 'Blocked', 'Completed': 'Done', 'Canceled': 'Canceled', 'Deferred': 'Deferred'}

ALL, TEAM, OWN, NO = 'all', 'team', 'own', 'no'


def access(create, read, edit, stream=None, delete=NO):
    return {'create': create, 'read': read, 'edit': edit, 'delete': delete, 'stream': stream or read}


ROLES = {
    # Kobo staff: everything of their teams, no delete
    'Internal Staff': {
        'data': {e: access('yes', TEAM, TEAM) for e in
                 ('Case', 'Task', 'CResponse', 'CProject', 'CSite', 'Contact', 'Account', 'CApplication',
                  'CResponder', 'CActivity', 'CActivityLocation', 'CFocalPoint')}
        | {'CStandard': access('yes', ALL, ALL), 'CAdminArea': access('yes', ALL, ALL),
           'COrganisation': access('yes', ALL, ALL),
           'Team': {'read': ALL}, 'User': {'read': TEAM}},
        'assignmentPermission': TEAM, 'userPermission': TEAM, 'mentionPermission': TEAM,
        'exportPermission': 'no', 'massUpdatePermission': 'yes',
    },
    # Triages a project's requests: its cases, the requesters, assigns within the team
    'Support Triager': {
        'data': {'Case': access('yes', TEAM, TEAM), 'Contact': access('no', TEAM, NO),
                 'Account': access('no', TEAM, NO), 'Team': {'read': TEAM}, 'User': {'read': TEAM}},
        'assignmentPermission': TEAM, 'userPermission': TEAM, 'mentionPermission': TEAM,
        'exportPermission': 'no', 'massUpdatePermission': 'no',
    },
    # Partner organisation staff in a consortium: their project's cases
    'Partner Staff': {
        'data': {'Case': access('yes', TEAM, TEAM), 'Contact': access('no', TEAM, NO),
                 'Account': access('no', TEAM, NO), 'Team': {'read': TEAM}, 'User': {'read': TEAM}},
        'assignmentPermission': TEAM, 'userPermission': TEAM, 'mentionPermission': TEAM,
        'exportPermission': 'no', 'massUpdatePermission': 'no',
    },
    # Roster experts: their response's tasks and sites; edit their own tasks
    'Roster Expert': {
        'data': {'Task': access('yes', TEAM, OWN, TEAM), 'CResponse': access('no', TEAM, NO),
                 'CSite': access('no', TEAM, OWN, TEAM), 'CStandard': access('no', ALL, NO),
                 'Team': {'read': TEAM}, 'User': {'read': TEAM}},
        'assignmentPermission': TEAM, 'userPermission': TEAM, 'mentionPermission': TEAM,
        'exportPermission': 'no', 'massUpdatePermission': 'no',
    },
    # Volunteers: as roster experts, but can't create tasks or edit sites
    'Volunteer': {
        'data': {'Task': access('no', TEAM, OWN, TEAM), 'CResponse': access('no', TEAM, NO),
                 'CSite': access('no', TEAM, NO), 'CStandard': access('no', ALL, NO),
                 'Team': {'read': TEAM}, 'User': {'read': TEAM}},
        'assignmentPermission': NO, 'userPermission': TEAM, 'mentionPermission': TEAM,
        'exportPermission': 'no', 'massUpdatePermission': 'no',
    },
    # A cluster project's people (in its team). Access is per person, not per project: someone
    # in two projects has their role in both. The lead runs the project's sites and tasks
    'Cluster Lead': {
        'data': {'CProject': access('no', TEAM, TEAM), 'CSite': access('yes', TEAM, TEAM),
                 'Task': access('yes', TEAM, TEAM), 'CResponse': access('no', TEAM, NO),
                 'CResponder': access('no', TEAM, TEAM), 'CActivity': access('yes', TEAM, TEAM),
                 'CActivityLocation': access('yes', TEAM, TEAM), 'CFocalPoint': access('no', TEAM, NO),
                 'CStandard': access('no', ALL, NO), 'CAdminArea': access('no', ALL, NO),
                 'COrganisation': access('no', ALL, NO),
                 'Team': {'read': TEAM}, 'User': {'read': TEAM}},
        'assignmentPermission': TEAM, 'userPermission': TEAM, 'mentionPermission': TEAM,
        'exportPermission': 'no', 'massUpdatePermission': 'no',
    },
    # Registers and updates sites, makes tasks, edits their own tasks
    'Cluster Partner': {
        'data': {'CProject': access('no', TEAM, NO), 'CSite': access('yes', TEAM, TEAM),
                 'Task': access('yes', TEAM, OWN, TEAM), 'CResponse': access('no', TEAM, NO),
                 'CResponder': access('no', TEAM, NO), 'CActivity': access('yes', TEAM, OWN, TEAM),
                 'CActivityLocation': access('yes', TEAM, OWN, TEAM), 'CFocalPoint': access('no', TEAM, NO),
                 'CStandard': access('no', ALL, NO), 'CAdminArea': access('no', ALL, NO),
                 'COrganisation': access('no', ALL, NO),
                 'Team': {'read': TEAM}, 'User': {'read': TEAM}},
        'assignmentPermission': TEAM, 'userPermission': TEAM, 'mentionPermission': TEAM,
        'exportPermission': 'no', 'massUpdatePermission': 'no',
    },
    # Reads the project's sites and tasks, and posts notes on them
    'Cluster Viewer': {
        'data': {'CProject': access('no', TEAM, NO), 'CSite': access('no', TEAM, NO),
                 'Task': access('no', TEAM, NO), 'CResponse': access('no', TEAM, NO),
                 'CResponder': access('no', TEAM, NO), 'CActivity': access('no', TEAM, NO),
                 'CActivityLocation': access('no', TEAM, NO),  # not focal points: people's contacts
                 'CStandard': access('no', ALL, NO), 'CAdminArea': access('no', ALL, NO),
                 'COrganisation': access('no', ALL, NO),
                 'Team': {'read': TEAM}, 'User': {'read': TEAM}},
        'assignmentPermission': NO, 'userPermission': TEAM, 'mentionPermission': TEAM,
        'exportPermission': 'no', 'massUpdatePermission': 'no',
    },
    # Workflow F: a country's CSO coordinators (WHO's country office): its CSOs, their places,
    # focal points and updates, all of them whatever their sharing; tasks in the team
    'CSO Coordinator': {
        'data': {'CCso': access('yes', TEAM, TEAM), 'CPresence': access('yes', TEAM, TEAM),
                 'CCsoUpdate': access('yes', TEAM, TEAM), 'CFocalPoint': access('yes', TEAM, TEAM),
                 'Task': access('yes', TEAM, TEAM), 'CAdminArea': access('no', ALL, NO),
                 'COrganisation': access('no', ALL, NO), 'CResponse': access('no', TEAM, NO),
                 'Team': {'read': TEAM}, 'User': {'read': TEAM}},
        'assignmentPermission': TEAM, 'userPermission': TEAM, 'mentionPermission': TEAM,
        'exportPermission': 'no', 'massUpdatePermission': 'no',
    },
}

INT, A, B, EQ1, EQ2, POOL, GRANTS, ETC, WASH, CSO_KEN, CSO_UGA, CSO_NONE = TEAMS
# (username, name, role, teams). Response 1 only: roster-1, volunteer-2; Response 2 only:
# volunteer-1; both: roster-2. Cluster projects of Response 1: ETC (lead, partner), WASH (viewer)
USERS = [
    ('triager', 'Tess Triager', 'Support Triager', [A, B]),
    ('staff-1', 'Sam Staff', 'Internal Staff', [INT, A, EQ1, EQ2, POOL]),
    ('staff-2', 'Sasha Staff', 'Internal Staff', [INT, B, GRANTS]),  # reviews applications (Workflow D)
    ('partner-a', 'Pat Partner-A', 'Partner Staff', [A]),
    ('partner-b', 'Pam Partner-B', 'Partner Staff', [B]),
    ('roster-1', 'Rui Roster', 'Roster Expert', [EQ1]),
    ('roster-2', 'Rana Roster', 'Roster Expert', [EQ1, EQ2]),
    ('volunteer-1', 'Vic Volunteer', 'Volunteer', [EQ2]),
    ('volunteer-2', 'Val Volunteer', 'Volunteer', [EQ1]),
    ('cluster-lead', 'Cleo Lead', 'Cluster Lead', [ETC]),
    ('cluster-partner', 'Cai Partner', 'Cluster Partner', [ETC]),
    ('cluster-viewer', 'Vera Viewer', 'Cluster Viewer', [WASH]),
    ('cso-kenya', 'Kendi Coordinator', 'CSO Coordinator', [CSO_KEN]),
    ('cso-uganda', 'Ugo Coordinator', 'CSO Coordinator', [CSO_UGA]),
]


def find(espo, entity, attr, value):
    return espo.find(entity, attr, value)


def ensure(espo, entity, attr, value, body, update=False):
    row = find(espo, entity, attr, value)
    if row is None:
        row = espo.call('POST', f'/{entity}', body=body)
        print(f'{entity} created: {value}')
    elif update:
        espo.call('PUT', f'/{entity}/{row["id"]}', body=body)
    return row


def metadata(espo, key):
    return espo.call('GET', '/Metadata', {'key': key}) or {}


def every(espo, entity, select, **where):
    """All records of an entity, 200 a page (EspoCRM's most)."""
    out, offset = [], 0
    while True:
        page = espo.call('GET', f'/{entity}', {'maxSize': 200, 'offset': offset, 'select': select, **where})['list']
        out += page
        offset += 200
        if len(page) < 200:
            return out


def ensure_field(espo, entity, name, spec):
    defs = metadata(espo, f'entityDefs.{entity}.fields')
    # Custom fields of EspoCRM's own entities get a "c" prefix; a custom entity's don't
    custom = metadata(espo, f'scopes.{entity}').get('isCustom')
    full = name if custom else 'c' + name[0].upper() + name[1:]
    body = {'label': spec.get('label', name[0].upper() + name[1:]), **{k: v for k, v in spec.items() if k != 'label'}}
    if full in defs:
        espo.call('PUT', f'/Admin/fieldManager/{entity}/{full}', body=body)
    else:
        espo.call('POST', f'/Admin/fieldManager/{entity}', body={'name': name, **body})
        print(f'field created: {entity}.{full}')
    return full


def ensure_entities(espo):
    scopes = metadata(espo, 'scopes')
    for name, spec in ENTITIES.items():
        if f'C{name}' not in scopes:
            espo.call('POST', '/EntityManager/action/createEntity', body={
                'name': name, 'type': 'Base', 'labelSingular': spec.get('label', name), 'labelPlural': spec['labelPlural'],
                'stream': spec.get('stream', True), 'iconClass': spec['iconClass']})
            print(f'entity created: C{name}')
        status = spec.get('statusField', 'status' if 'status' in spec['fields'] else None)
        if status:
            espo.call('POST', '/EntityManager/action/updateEntity', body={'name': f'C{name}', 'statusField': status})
        for field, fspec in spec['fields'].items():
            ensure_field(espo, f'C{name}', field, fspec)
    i18n = None
    for entity, link, foreign, link_foreign, kind in LINKS:
        if link not in metadata(espo, f'entityDefs.{entity}.links'):
            espo.call('POST', '/EntityManager/action/createLink', body={
                'entity': entity, 'link': link, 'linkForeign': link_foreign, 'entityForeign': foreign,
                'linkType': kind, 'label': link_label(link), 'labelForeign': link_label(link_foreign),
                'relationName': None})
            print(f'link created: {entity}.{link} -> {foreign}.{link_foreign}')
            continue
        i18n = i18n or espo.call('GET', '/I18n')
        # On EspoCRM's own entities a custom link's name gets a "c" (Task.cResponse)
        on_foreign = link_foreign if foreign[0] == 'C' and foreign[1].isupper() else 'c' + link_foreign[0].upper() + link_foreign[1:]
        if any(((i18n.get(e) or {}).get('links') or {}).get(name) != link_label(label_of)
               for e, name, label_of in ((entity, link, link), (foreign, on_foreign, link_foreign))):  # made before
            espo.call('POST', '/EntityManager/action/updateLink', body={  # labels were split into words
                'entity': entity, 'link': link, 'entityForeign': foreign, 'linkForeign': on_foreign,
                'label': link_label(link), 'labelForeign': link_label(link_foreign)})
            print(f'link labels: {entity}.{link} "{link_label(link)}", {foreign}.{link_foreign} "{link_label(link_foreign)}"')


def link_label(link):
    """leadOrganisation -> "Lead organisation", as the fields' labels are."""
    words = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', link).split(' ')
    return ' '.join([words[0].capitalize()] + [w.lower() for w in words[1:]])


def ensure_task_board(espo):
    status = metadata(espo, 'entityDefs.Task.fields.status')
    espo.call('PUT', '/Admin/fieldManager/Task/status', body={
        'type': 'enum', 'options': TASK_STATUS, 'translatedOptions': TASK_LABELS, 'default': 'Backlog',
        'style': {**status.get('style', {}), 'Blocked': 'danger', 'Backlog': 'default'},
        'notActualOptions': ['Completed', 'Canceled', 'Deferred']})
    espo.call('POST', '/EntityManager/action/updateEntity', body={
        'name': 'Task', 'kanbanViewMode': True, 'statusField': 'status',
        'kanbanStatusIgnoreList': ['Canceled', 'Deferred']})
    print('Task: board columns, Kanban on')
    # A task's parent (EspoCRM's own "Parent" field, which takes a Case already) can be a
    # Site or a responding organisation too; they get a Tasks panel
    parent = metadata(espo, 'entityDefs.Task.fields.parent')
    ours = ['CSite', 'CResponder']
    if not set(ours) <= set(parent.get('entityList', [])):
        espo.call('POST', '/EntityManager/action/updateLink', body={
            'entity': 'Task', 'link': 'parent', 'linkForeign': 'tasks',
            'parentEntityTypeList': sorted(set(parent.get('entityList', [])) | set(ours)), 'foreignLinkEntityTypeList': ours})
        print('Task: a parent can be a Site or a responding organisation')


def ensure_formulas(espo):
    """espo/formula/<Entity>.<scriptType>.formula, e.g. Case.beforeSaveApiScript.formula;
    _agent-guard.formula goes first in the API Before Save Script of AGENT_GUARDED (its
    stage block only where the entity has a stage)."""
    by_entity = {}
    for path in sorted((ROOT / 'espo' / 'formula').glob('[!_]*.formula')):
        entity, kind = path.stem.split('.')
        by_entity.setdefault(entity, {})[kind] = path.read_text()
    guard = (ROOT / 'espo' / 'formula' / '_agent-guard.formula').read_text()
    code = (ROOT / 'espo' / 'formula' / '_code.formula').read_text()
    for entity, prefix in CODES.items():
        scripts = by_entity.setdefault(entity, {})
        snippet = code.replace('FIELD', code_field(entity)).replace('PREFIX', prefix).replace('ENTITY', entity)
        scripts['beforeSaveCustomScript'] = snippet + '\n' + scripts.get('beforeSaveCustomScript', '')
    for entity in AGENT_GUARDED:
        g = guard
        if 'stage' not in metadata(espo, f'entityDefs.{entity}.fields'):
            g = re.sub(r'\n *// stage:begin.*?// stage:end\n', '\n', g, flags=re.S)
        scripts = by_entity.setdefault(entity, {})
        scripts['beforeSaveApiScript'] = g + '\n' + scripts.get('beforeSaveApiScript', '')
    for entity, scripts in by_entity.items():
        espo.call('POST', '/EntityManager/action/formula', body={'scope': entity, 'data': scripts})
        print(f'formula: {entity} ({", ".join(scripts)})')


def ensure_layout_fields(espo, entity, names, panel='Details'):
    """Add fields to the first panel of the detail layout if they aren't on it (and drop
    cells for fields that don't exist, e.g. from an earlier run with a wrong name)."""
    detail = espo.call('GET', f'/{entity}/layout/detail')
    fields = metadata(espo, f'entityDefs.{entity}.fields')
    stale = False
    for p in detail:
        for row in p.get('rows', []):
            for i, c in enumerate(row):
                if c and c.get('name') not in fields:
                    row[i], stale = False, True
    have = {c['name'] for p in detail for row in p.get('rows', []) for c in row if c}
    missing = [n for n in names if n not in have]
    if not missing:
        if stale:
            espo.call('PUT', f'/{entity}/layout/detail', body=detail)
        return
    rows = [[{'name': n} for n in missing[i:i + 2]] for i in range(0, len(missing), 2)]
    detail[0].setdefault('rows', []).extend(r + [False] * (2 - len(r)) for r in rows)
    espo.call('PUT', f'/{entity}/layout/detail', body=detail)
    print(f'layout: {entity} detail + {", ".join(missing)}')


def ensure_layouts(espo):
    ensure_layout_fields(espo, 'CResponse', ['status', 'emergencyType', 'country', 'lead', 'startDate', 'endDate'])
    ensure_layout_fields(espo, 'CProject', ['cluster', 'status', 'response', 'lead', 'startDate', 'endDate'])
    ensure_layout_fields(espo, 'CResponder', ['response', 'organisation', 'organisationOther', 'acronym', 'orgType',
                                              'clusters', 'status', 'focalPoint', 'contact', 'focalPointPhone',
                                              'lastReport', 'registrationKey'])
    ensure_layout_fields(espo, 'CActivity', ['response', 'project', 'leadOrganisation', 'leadOrganisationOther',
                                             'implementingOrganisation', 'implementingOrganisationOther', 'responder',
                                             'sector', 'sectorOther', 'activityType', 'activityTypeOther', 'title', 'status',
                                             'startDate', 'endDate', 'reportDate', 'resourceType', 'resourceTypeOther',
                                             'resourceUnit', 'resourceUnitOther', 'comments', 'resourceUrl'])
    ensure_layout_fields(espo, 'CActivity', ['communities', 'quantity', 'budget', 'peopleTargeted', 'peopleReached', 'dataChecks'])
    ensure_layout_fields(espo, 'CActivityLocation', ['activity', 'project', 'response', 'parish', 'community', 'site',
                                                     'locationType', 'locationTypeOther', 'locationComments', 'quantity',
                                                     'budget', 'populationTargeted', 'populationReached',
                                                     'populationGroups', 'populationGroupsOther', 'dataChecks'])
    ensure_layout_fields(espo, 'CActivityLocation', list(group_fields()))
    ensure_layout_fields(espo, 'CFocalPoint', ['activity', 'emailAddress', 'phone', 'jobTitle'])
    ensure_layout_fields(espo, 'COrganisation', ['code', 'orgType'])
    ensure_layout_fields(espo, 'CAdminArea', ['pcode', 'level', 'parentPcode', 'country'])
    ensure_layout_fields(espo, 'CCso', ['acronym', 'csoType', 'csoTypeOther', 'identities', 'countryRegistered', 'otherCountries',
                                        'countries', 'levels', 'sharing', 'listed', 'sharedContact', 'lastProfile', 'verified',
                                        'organisation'])
    ensure_layout_fields(espo, 'CCso', ['settings', 'settingsOther', 'populations', 'populationsOther', 'stages', 'roles',
                                        'rolesOther', 'rolesCholera', 'rolesCholeraOther', 'hazards', 'hazardsOther',
                                        'rolesWithSupport', 'rolesWithSupportOther', 'rolesWithSupportCholera', 'mechanisms',
                                        'mechanismsOther', 'offers', 'offersOther', 'seeks', 'seeksOther', 'connectVia',
                                        'connectViaOther', 'updateKey'])
    ensure_layout_fields(espo, 'CPresence', ['cso', 'adminArea', 'country', 'pcode1', 'pcode2', 'pcode3', 'latitude', 'longitude',
                                             'pcodeStatus', 'current', 'csoType', 'listed'])
    ensure_layout_fields(espo, 'CCsoUpdate', ['cso', 'status', 'adminArea', 'locality', 'country', 'pcode1', 'pcode2', 'pcode3',
                                              'latitude', 'longitude', 'pcodeStatus', 'roles', 'rolesOther', 'rolesCholera',
                                              'rolesCholeraOther', 'populations', 'populationsOther', 'facility', 'needs',
                                              'needsOther', 'needsNote', 'response', 'keyCheck', 'superseded', 'current',
                                              'dataChecks'])
    ensure_layout_fields(espo, 'CFocalPoint', ['cso', 'current'])
    ensure_layout_fields(espo, 'CSite', ['siteCode', 'siteType', 'status', 'region', 'response', 'project', 'standard', 'installedAt',
                                         'lastVisit', 'latitude', 'longitude', 'equipment', 'photos'])
    ensure_layout_fields(espo, 'CStandard', ['code', 'category', 'source', 'requirement'])
    ensure_layout_fields(espo, 'Task', ['cResponse', 'cProject'])  # EspoCRM's own entity: c-prefixed
    ensure_layout_fields(espo, 'Contact', ['cProfileType', 'cAvailability'])
    ensure_layout_fields(espo, 'Case', ['cSource'])
    for entity, cols in {'CResponse': ['name', 'code', 'status', 'emergencyType', 'country', 'lead', 'teams'],
                         'CProject': ['name', 'code', 'cluster', 'status', 'response', 'lead', 'teams'],
                         'CResponder': ['name', 'code', 'organisation', 'clusters', 'status', 'lastReport', 'response'],
                         'CActivity': ['name', 'code', 'leadOrganisation', 'sector', 'activityType', 'status',
                                       'communities', 'peopleReached', 'startDate', 'dataChecks'],
                         'CActivityLocation': ['name', 'activity', 'parish', 'community', 'locationType',
                                               'populationTargeted', 'populationReached'],
                         'CFocalPoint': ['name', 'activity', 'emailAddress', 'phone', 'jobTitle'],
                         'COrganisation': ['name', 'code', 'orgType'],
                         'CAdminArea': ['name', 'pcode', 'level', 'parentPcode', 'country'],
                         'CSite': ['name', 'siteCode', 'siteType', 'status', 'region', 'project', 'lastVisit'],
                         'CStandard': ['name', 'code', 'category', 'source'],
                         'CCso': ['name', 'code', 'csoType', 'countries', 'sharing', 'lastProfile', 'teams'],
                         'CPresence': ['name', 'cso', 'adminArea', 'country', 'pcodeStatus', 'current'],
                         'CCsoUpdate': ['name', 'cso', 'status', 'adminArea', 'roles', 'needs', 'current', 'dataChecks', 'createdAt'],
                         }.items():
        espo.call('PUT', f'/{entity}/layout/list',
                  body=[{'name': n, **({'link': True} if n == 'name' else {})} for n in cols])
    # A response's page: its projects, tasks and sites below it; a project's, its sites and
    # tasks; a site's, its tasks
    espo.call('PUT', '/CResponse/layout/relationships', body=[{'name': 'projects'}, {'name': 'responders'},
                                                               {'name': 'tasks'}, {'name': 'sites'}])
    espo.call('PUT', '/CProject/layout/relationships', body=[{'name': 'sites'}, {'name': 'activities'}, {'name': 'tasks'}])
    espo.call('PUT', '/CSite/layout/relationships', body=[{'name': 'tasks'}, {'name': 'activityLocations'}])
    espo.call('PUT', '/CResponder/layout/relationships', body=[{'name': 'activities'}, {'name': 'tasks'}])
    espo.call('PUT', '/CActivity/layout/relationships', body=[{'name': 'locations'}, {'name': 'focalPoints'}])
    espo.call('PUT', '/COrganisation/layout/relationships', body=[{'name': 'activitiesLed'}, {'name': 'registrations'}])
    espo.call('PUT', '/CCso/layout/relationships', body=[{'name': 'presence'}, {'name': 'updates'}, {'name': 'focalPoints'}])
    kanban = [{'name': 'name', 'link': True}, {'name': 'cProject'}, {'name': 'cResponse'}, {'name': 'assignedUser'},
              {'name': 'dateEnd'}]
    espo.call('PUT', '/Task/layout/kanban', body=kanban)
    task_fields = metadata(espo, 'entityDefs.Task.fields')
    espo.call('PUT', '/Task/layout/filters',  # (without fields that don't exist, e.g. from an earlier run)
              body=sorted(f for f in set(espo.call('GET', '/Task/layout/filters') or []) | {'cResponse', 'cProject', 'status', 'assignedUser'}
                          if f in task_fields))
    print('layouts: lists, task board card and filters')

    # Agents: set up on the Agent's page, its routes and runs below it
    agent_fields = list(ENTITIES['Agent']['fields'])
    ensure_layout_fields(espo, 'CAgent', ['description'] + agent_fields)
    ensure_layout_fields(espo, 'CAgentRoute', ['agent', 'description', 'assignUser', 'assignAgent']
                         + list(ENTITIES['AgentRoute']['fields']))
    ensure_layout_fields(espo, 'CAgentRun', ['agent'] + list(ENTITIES['AgentRun']['fields']))
    for entity, cols in {'CAgent': ['name', 'mode', 'entity', 'trigger', 'model', 'version', 'activeSince'],
                         'CAgentRoute': ['name', 'agent', 'order', 'ruleWhen', 'moveToStage', 'createTask'],
                         'CAgentRun': ['createdAt', 'agent', 'recordName', 'status', 'route', 'routeBy', 'cost'],
                         'CApplication': ['name', 'code', 'account', 'country', 'stage', 'ddSanctions', 'ddRisk', 'assignedUser']
                         }.items():
        espo.call('PUT', f'/{entity}/layout/list',
                  body=[{'name': n, **({'link': True} if n in ('name', 'createdAt') else {})} for n in cols])
    espo.call('PUT', '/CAgent/layout/relationships', body=[{'name': 'routes'}, {'name': 'runs'}])

    # Applications: a board by stage
    ensure_layout_fields(espo, 'CApplication', ['stage', 'account', 'contact', 'country', 'registrationNumber', 'website',
                                                'amountRequested', 'noticeVersion', 'purpose', 'leadership', 'documents'])
    ensure_layout_fields(espo, 'CApplication', ['ddSanctions', 'ddRegistry', 'ddRisk', 'ddFlags', 'ddSanctionsDetail',
                                                'ddSummary'])
    espo.call('POST', '/EntityManager/action/updateEntity', body={
        'name': 'CApplication', 'kanbanViewMode': True, 'statusField': 'stage',
        'kanbanStatusIgnoreList': ['Approved', 'Rejected']})
    espo.call('PUT', '/CApplication/layout/kanban',
              body=[{'name': 'name', 'link': True}, {'name': 'account'}, {'name': 'ddRisk'}, {'name': 'assignedUser'}])
    print('layouts: agents, applications (board)')
    for entity in CODES:
        ensure_layout_fields(espo, entity, [code_field(entity)])


def backfill_codes(espo):
    """Records made before they had codes: saved once, so the formula gives them one (the
    field is read-only: the API can't set it)."""
    for entity in CODES:
        field, done = code_field(entity), set()
        while True:
            rows = espo.call('GET', f'/{entity}', {'maxSize': 100, 'select': 'id,name',
                                                   'where[0][type]': 'isNull', 'where[0][attribute]': field})['list']
            rows = [r for r in rows if r['id'] not in done]
            if not rows:
                break
            for r in rows:
                espo.call('PUT', f'/{entity}/{r["id"]}', body={'name': r['name']})
                done.add(r['id'])
            print(f'codes: {entity} {len(rows)}')
        left = espo.call('GET', f'/{entity}', {'maxSize': 1, 'select': 'id', 'where[0][type]': 'isNull',
                                               'where[0][attribute]': field})['total']
        if left:
            print(f'codes: {entity}: {left} record(s) still without a code')


# Resend's SMTP; DigitalOcean blocks ports 465 and 587
EMAIL = {'address': 'noreply@respond.kobolabs.dev', 'name': 'Kobo Respond',
         'host': 'smtp.resend.com', 'port': 2587, 'security': 'TLS', 'username': 'resend'}
EMAIL_KEY = ROOT / 'secrets' / 'resend.key'


def ensure_email(espo):
    if not EMAIL_KEY.exists():
        print(f'email: no {EMAIL_KEY.relative_to(ROOT)}, no outgoing email')
        return
    key = EMAIL_KEY.read_text().strip()
    # tests/run_all.sh turns the notification emails off for its run, the seed reruns included
    notify = os.environ.get('SEED_EMAIL_NOTIFICATIONS') != 'off'
    espo.call('PUT', '/Settings', body={
        'outboundEmailFromAddress': EMAIL['address'], 'outboundEmailFromName': EMAIL['name'],
        'outboundEmailIsShared': False, 'smtpServer': EMAIL['host'], 'smtpPort': EMAIL['port'],
        'smtpSecurity': EMAIL['security'], 'smtpAuth': True, 'smtpUsername': EMAIL['username'], 'smtpPassword': key,
        'assignmentEmailNotifications': notify,
        'assignmentEmailNotificationsEntityList': ['Case', 'Task', 'CResponse', 'CProject', 'CSite', 'CApplication'],
        'mentionEmailNotifications': notify})
    # EspoCRM sends its own emails (access info, notifications) through the group email
    # account whose address is the from address, not with the settings' SMTP
    account = {'name': f'{EMAIL["name"]} (system)', 'emailAddress': EMAIL['address'], 'fromName': EMAIL['name'],
               'status': 'Active', 'useImap': False, 'useSmtp': True, 'smtpIsShared': False,
               'smtpHost': EMAIL['host'], 'smtpPort': EMAIL['port'], 'smtpSecurity': EMAIL['security'],
               'smtpAuth': True, 'smtpAuthMechanism': 'login', 'smtpUsername': EMAIL['username'], 'smtpPassword': key}
    have = find(espo, 'InboundEmail', 'emailAddress', EMAIL['address'])
    if have:
        espo.call('PUT', f'/InboundEmail/{have["id"]}', body=account)
    else:
        espo.call('POST', '/InboundEmail', body=account)
    print(f'email: from {EMAIL["address"]} by {EMAIL["host"]}:{EMAIL["port"]}; assignment and mention emails'
          + ('' if notify else ' off (SEED_EMAIL_NOTIFICATIONS=off)'))


def ensure_agents(espo, teams):
    """The example agents (agents/setup/*.json), made if missing, in their mode there
    (dry run or off): what someone changed on an agent since isn't overwritten."""
    for path in sorted((ROOT / 'agents' / 'setup').glob('*.json')):
        for spec in json.loads(path.read_text()):
            if find(espo, 'CAgent', 'name', spec['name']):
                continue
            make_agent(espo, spec, teams)
            print(f'agent created: {spec["name"]}')


def make_agent(espo, spec, teams):
    """An Agent and its routes from a spec as in agents/setup/*.json: route targets by name
    (assignUser: a user name, assignAgent: an agent's name), teams by name."""
    body = {k: v for k, v in spec.items() if k not in ('routes', 'teams')}
    body['teamsIds'] = [teams[t] for t in spec.get('teams', [])]
    agent = espo.call('POST', '/CAgent', body=body)
    for route in spec.get('routes', []):
        r = {k: v for k, v in route.items() if k not in ('assignUser', 'assignAgent')}
        if route.get('assignUser'):
            r['assignUserId'] = espo.find('User', 'userName', route['assignUser'])['id']
        if route.get('assignAgent'):
            r['assignAgentId'] = espo.find('CAgent', 'name', route['assignAgent'])['id']
        if isinstance(r.get('setFields'), dict):
            r['setFields'] = json.dumps(r['setFields'])
        espo.call('POST', '/CAgentRoute', body={**r, 'agentId': agent['id']})
    return agent


def ensure_users(espo, teams, roles):
    """The test users (USERS), their passwords in secrets/seed.secrets (kept across runs)."""
    path = ROOT / 'secrets' / 'seed.secrets'
    have = read_secrets('seed')
    out = dict(have)
    for username, full, role, team_names in USERS:
        first, last = full.split(' ', 1)
        key = pw_key(username)
        password = have.get(key) or secrets.token_urlsafe(14)
        body = {'userName': username, 'firstName': first, 'lastName': last, 'type': 'regular',
                'isActive': True, 'rolesIds': [roles[role]], 'teamsIds': [teams[t] for t in team_names],
                'defaultTeamId': teams[team_names[0]], 'emailAddress': f'delivered+{username}@resend.dev'}
        user = find(espo, 'User', 'userName', username)
        if user is None:
            espo.call('POST', '/User', body={**body, 'password': password})
            print(f'user created: {username} ({role}; {", ".join(team_names)})')
        else:  # teams and roles as defined here; the password too if it was lost
            espo.call('PUT', f'/User/{user["id"]}', body={**body, **({} if key in have else {'password': password})})
        out[key] = password
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.write_text(''.join(f'{k}={v}\n' for k, v in out.items()))
    path.chmod(0o600)
    print(f'users: {len(USERS)}, passwords in {path.relative_to(ROOT)}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default=URL)
    ap.add_argument('--users', action='store_true')
    args = ap.parse_args()
    espo = admin() if args.url == URL else Espo(args.url, basic=f'admin:{read_secrets()["ESPO_ADMIN_PASSWORD"]}')

    settings = espo.call('GET', '/Settings')
    espo.call('PUT', '/Settings', body={
        'assignmentNotificationsEntityList': sorted(set(settings.get('assignmentNotificationsEntityList') or [])
                                                    | {'Case', 'Task', 'CResponse', 'CProject', 'CSite', 'CApplication'}),
        # In global search, so the isolation tests (T8) search them too
        'globalSearchEntityList': sorted(set(settings.get('globalSearchEntityList') or [])
                                         | {'Case', 'Contact', 'Account', 'Task', 'CResponse', 'CProject', 'CSite', 'CStandard',
                                            'CApplication', 'CResponder', 'CActivity', 'COrganisation', 'CCso'}),
        'applicationName': 'Kobo requests and responses (test)'})
    print('settings: assignment notifications for Case, Task, Response, Project, Site, Application; global search')
    ensure_email(espo)

    ensure_entities(espo)
    for entity, link in OBSOLETE_LINKS:
        if link in metadata(espo, f'entityDefs.{entity}.links'):
            espo.call('POST', '/EntityManager/action/removeLink', body={'entity': entity, 'link': link})
            print(f'link removed: {entity}.{link}')
    for entity, names in OBSOLETE_FIELDS.items():
        defs = metadata(espo, f'entityDefs.{entity}.fields')
        for name in names:
            if name in defs:
                espo.call('DELETE', f'/Admin/fieldManager/{entity}/{name}')
                print(f'field removed: {entity}.{name}')
    for entity, fields in FIELDS.items():
        for name, spec in fields.items():
            ensure_field(espo, entity, name, spec)
    for entity in CODES:
        ensure_field(espo, entity, 'code', CODE_FIELD)
        filters = metadata(espo, f'entityDefs.{entity}.collection').get('textFilterFields') or ['name']
        if code_field(entity) not in filters:  # found by its code in the list's search box
            espo.call('POST', '/EntityManager/action/updateEntity',
                      body={'name': entity, 'textFilterFields': filters + [code_field(entity)]})
    ensure_task_board(espo)
    ensure_formulas(espo)
    ensure_layouts(espo)
    backfill_codes(espo)

    # Reference data: standards (no team: everyone with read access sees them)
    for std in json.loads((ROOT / 'espo' / 'seed' / 'data' / 'standards.json').read_text()):
        ensure(espo, 'CStandard', 'code', std['code'], std, update=True)
    # Admin areas (no team), one file per country: espo/seed/data/admin-areas-<iso3>.json,
    # its COD P-codes (Jamaica's from the Hurricane Melissa 5W form, ref/). Only what
    # differs is written; areas of that country no longer in the file are removed
    for path in sorted((ROOT / 'espo' / 'seed' / 'data').glob('admin-areas-*.json')):
        want = {a['pcode']: a for a in json.loads(path.read_text())}
        country = next(iter(want.values()))['country']
        have, offset = {}, 0
        while True:
            page = espo.call('GET', '/CAdminArea', {'maxSize': 200, 'offset': offset, 'select': 'name,pcode,level,parentPcode,country',
                                                   'where[0][type]': 'equals', 'where[0][attribute]': 'country',
                                                   'where[0][value]': country})['list']
            have.update({r['pcode']: r for r in page})
            offset += 200
            if len(page) < 200:
                break
        written = 0
        for code, area in want.items():
            if code not in have:
                espo.call('POST', '/CAdminArea', body=area)
                written += 1
            elif any(have[code].get(k) != v for k, v in area.items()):
                espo.call('PUT', f'/CAdminArea/{have[code]["id"]}', body=area)
                written += 1
        for code in set(have) - set(want):
            espo.call('DELETE', f'/CAdminArea/{have[code]["id"]}')
        print(f'admin areas {country}: {len(want)}, {written} written, {len(set(have) - set(want))} removed')
    # Organisations, as the 5W form lists them (by code; only what differs is written)
    have = {r['code']: r for r in every(espo, 'COrganisation', 'name,code,orgType')}
    written = 0
    for o in FIVEW['organisations']:
        body = {'name': o['label'], 'code': o['code'], 'orgType': o.get('org_type') or ''}
        if o['code'] not in have:
            espo.call('POST', '/COrganisation', body=body, headers={'X-Skip-Duplicate-Check': 'true'})
            written += 1
        elif any(have[o['code']].get(k) != v for k, v in body.items()):
            espo.call('PUT', f'/COrganisation/{have[o["code"]]["id"]}', body=body)
            written += 1
    print(f'organisations: {len(FIVEW["organisations"])}, {written} written')
    # Projects and organisations from before the Melissa form's sector codes (an old code,
    # or a label as the value): their sector's code
    old = {**OLD_CLUSTERS, 'Emergency Telecommunications': 'EMERGENCY_TELECOMS', 'WASH': 'WASH'}
    for row in espo.call('GET', '/CProject', {'maxSize': 200, 'select': 'cluster'})['list']:
        if row.get('cluster') in old:
            espo.call('PUT', f'/CProject/{row["id"]}', body={'cluster': old[row['cluster']]})
    for row in every(espo, 'CResponder', 'clusters'):
        if any(c in old for c in row.get('clusters') or []):
            espo.call('PUT', f'/CResponder/{row["id"]}', body={'clusters': sorted({old.get(c, c) for c in row['clusters']})})

    teams = {name: ensure(espo, 'Team', 'name', name, {'name': name})['id'] for name in TEAMS}
    roles = {}
    for name, spec in ROLES.items():
        # Access to entities defined elsewhere (a Kobo connection's, granted through the
        # bridge's MCP) is kept: the seed puts back only what it defines
        have = find(espo, 'Role', 'name', name)
        have = espo.call('GET', f'/Role/{have["id"]}') if have else {}
        mine = set(spec.get('data', {}))
        data = {**{e: v for e, v in (have.get('data') or {}).items() if e not in mine}, **spec.get('data', {})}
        fields = {**{e: v for e, v in (have.get('fieldData') or {}).items() if e not in mine}, **spec.get('fieldData', {})}
        roles[name] = ensure(espo, 'Role', 'name', name, {'name': name, **spec, 'data': data, 'fieldData': fields},
                             update=True)['id']
    print(f'teams: {len(teams)}, roles: {", ".join(roles)}')
    ensure_agents(espo, teams)

    if args.users:
        ensure_users(espo, teams, roles)

if __name__ == '__main__':
    main()

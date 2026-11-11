"""
The formulas' traits (espo/traits.py, plans/workflow-packs-plan.md phase 3), on every pack.
Offline:

    python3 -I tests/test_traits.py

What EspoCRM does with the scripts is the workflows' own tests' (cso, fivew, projects,
isolation): these check what the loader writes.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'espo'))
import traits  # noqa: E402
import workflows  # noqa: E402

PACKS = ['core', 'support', 'responses', 'roster', 'sites', 'grants', 'fivew', 'cso']


def custom(spec, entity):
    return workflows.scripts(spec)[entity]['beforeSaveCustomScript']


class Traits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = workflows.load(PACKS)

    def test_every_script_balanced(self):
        for entity, scripts in workflows.scripts(self.spec).items():
            for kind, text in scripts.items():
                bare = re.sub(r"'(?:[^'\\]|\\.)*'", "''", re.sub(r'//[^\n]*', '', text))
                self.assertEqual(bare.count('{'), bare.count('}'), f'{entity} {kind}')
                self.assertEqual(bare.count('('), bare.count(')'), f'{entity} {kind}')
                self.assertNotIn('// trait:', text, f'{entity} {kind}: a marker left')

    def test_order_before_block_after(self):
        s = custom(self.spec, 'CCsoUpdate')
        at = [s.index(x) for x in ('(trait portal_default)', 'Where (trait pcodes)', '(trait inherit)',
                                   "keyCheck = ifThenElse", '(trait checks)', '(trait supersede)')]
        self.assertEqual(at, sorted(at))

    def test_marker_places_a_trait(self):
        s = custom(self.spec, 'CPresence')  # inherit after its block: the CSO's countries first
        self.assertLess(s.index("record\\update('CCso', csoId, 'countries'"), s.index('(trait inherit)'))
        self.assertIn("entity\\isAttributeChanged('csoId') || entity\\isAttributeChanged('country'))) {\n    $teams", s)
        a = custom(self.spec, 'CActivity')  # its project found first, then inherit
        self.assertLess(a.index("projectId = $project"), a.index('(trait inherit)'))

    def test_cascade_on_the_parent(self):
        s = custom(self.spec, 'CCso')
        for child, link in (('CPresence', 'csoId='), ('CCsoUpdate', 'csoId='), ('Contact', 'cCsoId=')):
            self.assertIn(f"record\\findMany('{child}', 1000, 'createdAt', 'asc', '{link}', id)", s)
        self.assertGreater(s.index('(trait cascade'), s.index("record\\create('Account'"))
        p = custom(self.spec, 'CProject')  # the sites pack's cascade, on the responses pack's entity
        self.assertIn("record\\update('CSite', array\\at($rows, $i), 'teamsIds', teamsIds, 'responseId', responseId)", p)
        self.assertNotIn('(trait cascade', custom(workflows.load(['core', 'responses']), 'CProject'))

    def test_unless(self):
        s = custom(self.spec, 'CSite')
        self.assertIn("if (!projectId && responseId && (entity\\isNew() || entity\\isAttributeChanged('responseId'))) {", s)

    def test_trait_only_entity(self):
        self.assertIn("(trait inherit)", custom(self.spec, 'CFocalPoint'))

    def test_supersede(self):
        s = custom(self.spec, 'CCsoUpdate')
        self.assertIn("$counted = keyCheck == 'ok' || keyCheck == 'confirmed';", s)
        self.assertIn("if ($o != id && ($oc == 'ok' || $oc == 'confirmed')) {", s)
        self.assertTrue(s.rstrip().endswith('current = $counted && !superseded;'))
        plain = traits.supersede({'by': ['siteId']}, 'CVisit')
        self.assertIn('$counted = true;', plain)
        self.assertNotIn('$oc', plain)

    def test_checks_match_options(self):
        bad = {'checks': {'nope': 'true'}}
        with self.assertRaisesRegex(ValueError, "not dataChecks' options"):
            traits.check('CActivity', bad, self.spec['entities']['Activity']['fields'])
        with self.assertRaisesRegex(ValueError, 'unknown traits'):
            traits.check('CActivity', {'inherits': []}, None)
        with self.assertRaisesRegex(ValueError, 'needs the fields'):
            traits.check('CSite', {'pcodes': 'adminArea'}, self.spec['entities']['Site']['fields'])
        with self.assertRaisesRegex(ValueError, 'cascade with unless'):
            traits.cascades({'CX': {'inherit': [{'link': 'a', 'entity': 'CA', 'copy': [], 'cascade': True, 'unless': 'b'}]}})

    def test_teams_up(self):
        s = custom(self.spec, 'CResponder')
        self.assertIn("record\\update('Account', accountId, 'teamsIds', $teams);", s)
        self.assertIn("record\\update('Account', $left, 'teamsIds', $teams);", s)
        self.assertLess(s.index("accountId = $acc;"), s.index('(trait teams_up)'))  # after its block finds the Account

    def test_teams_from_clusters(self):
        r = custom(self.spec, 'CResponder')
        self.assertLess(r.index('(trait teams_from_clusters)'), r.index('(trait account_from_organisation)'))
        p = custom(self.spec, 'CProject')  # the project's side, made from the registration's trait
        self.assertIn("record\\update('CResponder', $o, 'teamsIds', $have);", p)
        self.assertNotIn('CResponder', custom(workflows.load(['core', 'responses']), 'CProject'))
        every = traits.teams_from_clusters({'all': True}, 'CAssessment')
        self.assertIn('if (true) {', every)
        self.assertNotIn("isAttributeChanged('clusters')", every)

    def test_quoting(self):
        self.assertEqual(traits.q("it's"), "'it\\'s'")


if __name__ == '__main__':
    unittest.main()

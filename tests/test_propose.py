"""
kobo-espo-bridge's propose() on this repo's forms, against their hand-written templates
(plans/kobo-connections-plan.md, phase 3). Offline:

    python3 -I tests/test_propose.py

Each difference is either a default to fix in propose() or listed here as a deliberate
choice of the hand-written template. site-visit.toml is a follow-up form (it updates
sites), which propose() doesn't do: follow-ups have no default.
"""
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(os.environ.get('KOBO_ESPO_BRIDGE_DIR', ROOT.parent / 'kobo-espo-bridge'))))
import bridge  # noqa: E402
import propose  # noqa: E402

# (form, template, entity, the fields EspoCRM has already that matter here)
FORMS = [
    ('support-request', 'support-request', 'Case', {}),
    ('volunteer-availability', 'volunteer', 'Contact', {}),
    ('site-registration', 'site-registration', 'CSite',
     {'response': 'link', 'standard': 'link', 'photos': 'attachmentMultiple'}),
]
# Chosen by hand, not guessable from the form
DELIBERATE = {
    ('site-registration', 'end'): 'registeredAt ("Registered"), not finishedAt',
    ('site-registration', 'installed'): 'installedAt, the field the seed made',
    ('support-request', 'description'): 'the description as a details line, which is the same thing',
}


def load(form, template, entity, existing):
    content = json.loads((ROOT / 'kobo' / 'forms' / f'{form}.json').read_text())
    hand = bridge.load_template(ROOT / 'kobo' / 'templates' / f'{template}.toml')
    got = propose.propose(content, entity, existing=existing)
    return hand, bridge.parse_template(got['template']), got


class AgainstHandWritten(unittest.TestCase):
    def test_fields(self):
        for form, template, entity, existing in FORMS:
            hand, prop, _ = load(form, template, entity, existing)
            mine = {f['kobo']: f for f in prop['field'] if f.get('kobo')}
            for f in hand['field']:
                if (form, f['kobo']) in DELIBERATE:
                    continue
                with self.subTest(form=form, question=f['kobo']):
                    self.assertIn(f['kobo'], mine)
                    self.assertEqual(mine[f['kobo']]['espo'], f['espo'])
                    if f.get('type'):  # where the hand-written one says; else EspoCRM's field decides
                        self.assertEqual(mine[f['kobo']].get('type'), f['type'])
            with self.subTest(form=form, check='nothing more'):
                extra = set(mine) - {f['kobo'] for f in hand['field']} - {q for (fm, q) in DELIBERATE if fm == form}
                self.assertEqual(extra, set())

    def test_record(self):
        for form, template, entity, existing in FORMS:
            hand, prop, _ = load(form, template, entity, existing)
            with self.subTest(form=form):
                for key in ('match', 'media'):
                    self.assertEqual(prop['record'].get(key), hand['record'].get(key), key)
                self.assertEqual(prop.get('requester'), hand.get('requester'))
                if form != 'support-request':  # its name is "{category}: {summary}", by choice
                    self.assertEqual(prop['record'].get('name'), hand['record'].get('name'))
                self.assertTrue(set(prop['record'].get('required', [])) <= set(hand['record'].get('required', [])))

    def test_left_out(self):
        _, _, got = load(*FORMS[2])
        self.assertEqual(dict(got['left_out']).keys(), {'standard_requirement', 'standard_note'})
        self.assertTrue(any(w.startswith('standard: a link from a list file') for w in got['warnings']))


if __name__ == '__main__':
    unittest.main()

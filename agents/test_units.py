"""Offline tests for the agents' code: sanctions matching, geocoding, rules, schedules, checking model output.

    python3 -I agents/test_units.py
"""
import calendar
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402
import tools  # noqa: E402
from runner import fill, matches, schedule_slot  # noqa: E402


class Sanctions(unittest.TestCase):
    def level(self, **data):
        return tools.sanctions(data)[0]['ddSanctions']

    def test_exact_name_and_alias(self):
        self.assertEqual(self.level(accountName='Crimson Horizon Relief Brigade'), 'match')
        self.assertEqual(self.level(accountName='CHRB'), 'match')

    def test_case_accents_punctuation_legal_form(self):
        self.assertEqual(self.level(accountName='crimson horizon relief brigade ltd.'), 'match')
        self.assertEqual(self.level(accountName='Obsidian Délta Holdings SARL'), 'match')

    def test_word_order_and_misspelling_are_possible_matches(self):
        self.assertEqual(self.level(leadership='Quentin Vexly'), 'possible_match')
        self.assertEqual(self.level(leadership='Marlow Quentin Vexley'), 'possible_match')

    def test_unrelated_is_clear(self):
        self.assertEqual(self.level(accountName='Clear Water Partners', leadership='Jane Example\nAmina Diallo'), 'clear')


class Geocode(unittest.TestCase):
    """The geocode tool against a stand-in for the geocoder's API (its responses' shape)."""

    def setUp(self):
        self.calls, self.real = [], tools.geocoder
        tools._iso2.clear()

        def fake(path, body=None):
            self.calls.append((path, body))
            if path == '/countries':
                return [{'code': 'KE', 'iso3': 'KEN'}, {'code': 'UG', 'iso3': 'UGA'}]
            if self.down:
                raise tools.urllib.error.URLError('down')
            if body['latitude'] > 40:
                return {'success': False, 'error': 'Point outside known boundaries'}
            return {'success': True, 'adm0_pcode': 'KE', 'adm1_pcode': 'KE047', 'adm1_name': 'Nairobi',
                    'adm2_pcode': 'KE047288', 'adm2_name': 'Kamukunji'}
        self.down = False
        tools.geocoder = fake

    def tearDown(self):
        tools.geocoder = self.real

    def test_pcodes_of_each_level(self):
        values, line = tools.geocode({'latitude': -1.28, 'longitude': 36.84, 'country': 'KEN'})
        self.assertEqual(values, {'pcode1': 'KE047', 'pcode2': 'KE047288', 'pcodeStatus': 'done'})
        self.assertEqual(self.calls[-1][1]['country'], 'KE')  # ISO3 to the geocoder's ISO2
        self.assertIn('Kamukunji, Nairobi', line)

    def test_outside(self):
        self.assertEqual(tools.geocode({'latitude': 48.8, 'longitude': 2.3, 'country': 'KEN'})[0], {'pcodeStatus': 'outside'})

    def test_down_or_no_pin_writes_nothing(self):
        self.down = True
        self.assertEqual(tools.geocode({'latitude': -1.28, 'longitude': 36.84, 'country': 'KEN'})[0], {})
        self.assertEqual(tools.geocode({'country': 'KEN'})[0], {})


class Rules(unittest.TestCase):
    def route(self, op, value, field='status'):
        return {'ruleField': field, 'ruleOp': op, 'ruleValue': value}

    def test_ops(self):
        self.assertTrue(matches(self.route('equals', 'needs_repair'), {'status': 'needs_repair'}))
        self.assertTrue(matches(self.route('in', 'match, possible_match'), {'status': 'possible_match'}))
        self.assertTrue(matches(self.route('contains', 'SICK'), {'status': 'two got sick'}))
        self.assertFalse(matches(self.route('equals', 'x'), {}))
        self.assertTrue(matches(self.route('in', 'new_org'), {'status': ['adverse_media', 'new_org']}))

    def test_safety_pattern(self):
        import json
        spec = json.loads((Path(__file__).parents[1] / 'workflows' / 'sites' / 'agents.json').read_text())
        rule = next(r for a in spec for r in a['routes'] if r['name'] == 'urgent_safety')
        for text in ['two children got sick', 'Water contaminated after the flood', 'un enfant est malade',
                     'hay heridos', 'the wall collapsed']:
            self.assertTrue(matches(rule, {'text': text}), text)
        for text in ['Routine visit, all fine', 'The solar battery is dead', 'Will come back next week', 'skill share']:
            self.assertFalse(matches(rule, {'text': text}), text)

    def test_fill(self):
        self.assertEqual(fill('Urgent: {name} ({missing})', {'name': 'Well 1'}), 'Urgent: Well 1 ()')


class Schedule(unittest.TestCase):
    def slot(self, now, **agent):
        t = calendar.timegm(time.strptime(now, '%Y-%m-%d %H:%M'))
        return schedule_slot(agent, t)

    def test_every_hour_day_week(self):  # 2026-11-04 is a Wednesday
        self.assertEqual(self.slot('2026-11-04 10:20', scheduleEvery='hour', scheduleAt='00:15'), '2026-11-04 10:15:00')
        self.assertEqual(self.slot('2026-11-04 10:10', scheduleEvery='hour', scheduleAt='00:15'), '2026-11-04 09:15:00')
        self.assertEqual(self.slot('2026-11-04 10:00', scheduleEvery='day', scheduleAt='06:00'), '2026-11-04 06:00:00')
        self.assertEqual(self.slot('2026-11-04 05:59', scheduleEvery='day', scheduleAt='06:00'), '2026-11-03 06:00:00')
        week = {'scheduleEvery': 'week', 'scheduleWeekday': 'Mon', 'scheduleAt': '06:00'}
        self.assertEqual(self.slot('2026-11-04 10:00', **week), '2026-11-02 06:00:00')
        self.assertEqual(self.slot('2026-11-02 06:00', **week), '2026-11-02 06:00:00')
        self.assertEqual(self.slot('2026-11-02 05:00', **week), '2026-10-26 06:00:00')
        self.assertEqual(self.slot('2026-11-08 23:00', **week), '2026-11-02 06:00:00')  # a Sunday

    def test_not_set_up(self):
        self.assertIsNone(self.slot('2026-11-04 10:00', scheduleEvery='', scheduleAt='06:00'))
        self.assertIsNone(self.slot('2026-11-04 10:00', scheduleEvery='day', scheduleAt='6am'))
        self.assertIsNone(self.slot('2026-11-04 10:00', scheduleEvery='day', scheduleAt='25:00'))


class Output(unittest.TestCase):
    schema = llm.output_schema(['ddRisk', 'ddFlags', 'ddSummary', 'n', 'ok'], {
        'ddRisk': {'type': 'enum', 'options': ['', 'low', 'high']},
        'ddFlags': {'type': 'multiEnum', 'options': ['new_org', 'adverse_media']},
        'ddSummary': {'type': 'text'}, 'n': {'type': 'int'}, 'ok': {'type': 'bool'}}, ['review', 'ok'])

    def good(self, **kw):
        return {'route': 'review', 'reason': 'r', 'ddRisk': 'low', 'ddFlags': [], 'ddSummary': 's', 'n': 1, 'ok': True, **kw}

    def test_valid(self):
        self.assertEqual(llm.check(self.good(), self.schema)[1], [])

    def test_coerced(self):
        out, errors = llm.check(self.good(route='REVIEW', ddRisk='Low', ddFlags='new_org, adverse_media', n='3',
                                          ok='false', extra='x'), self.schema)
        self.assertEqual(errors, [])
        self.assertEqual((out['route'], out['ddRisk'], out['ddFlags'], out['n'], out['ok']),
                         ('review', 'low', ['new_org', 'adverse_media'], 3, False))
        self.assertNotIn('extra', out)

    def test_invalid(self):
        _, errors = llm.check(self.good(route='approve', ddFlags=['bad']), self.schema)
        self.assertEqual(len(errors), 2)
        _, errors = llm.check({'route': 'ok'}, self.schema)
        self.assertIn('reason is missing', errors)
        self.assertEqual(llm.check(None, self.schema)[1], ['the output is not a JSON object'])

    def test_json_in_prose(self):
        self.assertEqual(llm.parse_json('Here: ```json\n{"a": 1}\n```'), {'a': 1})

    def test_corrections(self):
        class Flaky:
            n = 0

            def complete(self, alias, system, messages, schema, server_tools, usage):
                Flaky.n += 1
                return ('{"route": "nope"}' if Flaky.n == 1 else
                        '{"route": "ok", "reason": "r", "ddRisk": "high", "ddFlags": [], "ddSummary": "", "n": 0, "ok": 1}'), ''
        out = llm.decide(Flaky(), 'x', 's', [], self.schema, [], llm.Usage())
        self.assertEqual((Flaky.n, out['route']), (2, 'ok'))


if __name__ == '__main__':
    unittest.main()

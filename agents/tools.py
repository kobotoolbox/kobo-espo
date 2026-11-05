"""Code tools for agents: checks that must give the same answer every time (plan §2).

A tool takes the record's read fields and returns field values for the agent's output
(only those in its outputFields are written) plus a line for the run's note. Server tools
(web_search, web_fetch) aren't here: the model calls them (llm.py).

    sanctions   the organisation and its leaders against the sanctions lists
    registry    the organisation in a registry (not built yet: "not checked")

The lists are JSON files, [{"name", "aliases": [...], "list", "ref"}], from
AGENTS_SANCTIONS_LISTS (comma-separated paths; default the fixture). The fixture holds
made-up names only, for the tests. Downloading the real lists (UN, OFAC, EU) is a later step.
"""
import difflib
import json
import os
import re
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / 'data' / 'sanctions-fixture.json'
# Legal forms and filler words that don't tell organisations apart
NOISE = {'the', 'ltd', 'limited', 'inc', 'llc', 'plc', 'sarl', 'sa', 'gmbh', 'ngo', 'asbl', 'co', 'company', 'of', 'and',
         'et', 'de', 'la', 'le', 'des', 'du', 'y', 'el'}
# A low threshold on purpose: a possible match costs a person a check, a miss is worse
POSSIBLE = 0.82


def normalise(name):
    s = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode().casefold()
    words = [w for w in re.split(r'[^a-z0-9]+', s) if w and w not in NOISE]
    return ' '.join(words)


def similarity(a, b):
    """The better of the plain and the word-order-insensitive ratios."""
    plain = difflib.SequenceMatcher(None, a, b).ratio()
    ordered = difflib.SequenceMatcher(None, ' '.join(sorted(a.split())), ' '.join(sorted(b.split()))).ratio()
    return max(plain, ordered)


def load_lists():
    paths = [p for p in os.environ.get('AGENTS_SANCTIONS_LISTS', str(FIXTURE)).split(',') if p]
    entries = []
    for p in paths:
        entries.extend(json.loads(Path(p).read_text()))
    return entries


def names_to_check(data):
    names = [data.get('accountName'), data.get('name')]
    names += [ln.strip() for ln in (data.get('leadership') or '').splitlines()]
    return [n for n in dict.fromkeys(names) if n and normalise(n)]


def sanctions(data):
    entries = load_lists()
    best = []
    for name in names_to_check(data):
        n = normalise(name)
        for e in entries:
            for listed in [e['name']] + e.get('aliases', []):
                exact = normalise(listed) == n
                score = 1.0 if exact else similarity(n, normalise(listed))
                if score >= POSSIBLE:
                    best.append((exact, score, name, e, listed))
    if not best:
        return {'ddSanctions': 'clear', 'ddSanctionsDetail': f'No match for {", ".join(names_to_check(data))} '
                f'on {len(entries)} listed names.'}, 'Sanctions: clear.'
    best.sort(key=lambda b: (not b[0], -b[1]))
    # Only the same name (once normalised) is a match: reordered or misspelt, a person checks
    level = 'match' if best[0][0] else 'possible_match'
    detail = '\n'.join(f'{name} ~ {listed} ({e["list"]} {e.get("ref", "")}, score {score:.2f})'.replace(' ,', ',')
                       for exact, score, name, e, listed in best[:5])
    return {'ddSanctions': level, 'ddSanctionsDetail': detail}, f'Sanctions: {level.replace("_", " ")}.'


def registry(data):
    return {'ddRegistry': 'not_checked'}, 'Registry: not checked (no registry source yet).'


TOOLS = {'sanctions': sanctions, 'registry': registry}
SERVER_TOOLS = {'web_search', 'web_fetch'}


def run(names, data):
    """(field values, note lines) from the agent's code tools."""
    values, lines = {}, []
    for name in names or []:
        if name in TOOLS:
            v, line = TOOLS[name](data)
            values.update(v)
            lines.append(line)
    return values, lines

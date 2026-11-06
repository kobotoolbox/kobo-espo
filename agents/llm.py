"""The model side of a run: the output schema from the Agent's setup, checking what comes
back, and the providers (the Claude API, and a fake one for the tests).

The model only ever returns {"route": <one of the route names>, "reason": ..., <the
Agent's outputFields>}. Whatever comes back is checked here (plan §4, from Ponto's
policy.py): values coerced to the schema's types where that's unambiguous, unknown keys
dropped, then validated. If it's still invalid, the errors go back to the model to correct,
up to CORRECTIONS times, before the attempt counts as failed.
"""
import json
import re
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = tomllib.loads((HERE / 'models.toml').read_text())
CORRECTIONS = 2


class ModelError(Exception):
    pass


def field_schema(spec):
    t = spec.get('type')
    if t == 'enum':
        return {'type': 'string', 'enum': [o for o in spec.get('options', []) if o]}
    if t == 'multiEnum':
        return {'type': 'array', 'items': {'type': 'string', 'enum': [o for o in spec.get('options', []) if o]}}
    if t == 'array':
        return {'type': 'array', 'items': {'type': 'string'}}
    if t == 'int':
        return {'type': 'integer'}
    if t in ('float', 'currency'):
        return {'type': 'number'}
    if t == 'bool':
        return {'type': 'boolean'}
    return {'type': 'string'}


def output_schema(output_fields, field_defs, route_names):
    props = {'route': {'type': 'string', 'enum': route_names},
             'reason': {'type': 'string'}}
    for f in output_fields:
        props[f] = field_schema(field_defs.get(f, {}))
    return {'type': 'object', 'properties': props, 'required': list(props), 'additionalProperties': False}


_TRUE, _FALSE = {'true', 'yes', '1'}, {'false', 'no', '0', ''}


def coerce(value, schema):
    t = schema.get('type')
    if t == 'boolean' and isinstance(value, str) and value.strip().casefold() in _TRUE | _FALSE:
        return value.strip().casefold() in _TRUE
    if t == 'boolean' and value in (0, 1) and not isinstance(value, bool):
        return bool(value)
    if t == 'integer' and isinstance(value, str) and value.strip().lstrip('-').isdigit():
        return int(value)
    if t == 'number' and isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    if t == 'string' and isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if t == 'string' and isinstance(value, str) and 'enum' in schema and value not in schema['enum']:
        low = value.strip().casefold().replace(' ', '_')
        return next((o for o in schema['enum'] if o.casefold() == low), value)
    if t == 'array' and isinstance(value, str):
        value = [v.strip() for v in value.split(',') if v.strip()]
    if t == 'array' and isinstance(value, list):
        return [coerce(v, schema.get('items', {})) for v in value]
    return value


def check(data, schema):
    """(coerced data, errors). Unknown keys are dropped: the model can't add fields."""
    if not isinstance(data, dict):
        return None, ['the output is not a JSON object']
    out, errors = {}, []
    for k, v in data.items():
        if k in schema['properties']:
            out[k] = coerce(v, schema['properties'][k])
    for k, s in schema['properties'].items():
        if k not in out:
            errors.append(f'{k} is missing')
            continue
        v = out[k]
        want = {'string': str, 'integer': int, 'number': (int, float), 'boolean': bool, 'array': list}[s['type']]
        if not isinstance(v, want) or (s['type'] in ('integer', 'number') and isinstance(v, bool)):
            errors.append(f'{k} must be {s["type"]}')
        elif 'enum' in s and v not in s['enum']:
            errors.append(f'{k} must be one of {", ".join(s["enum"])}')
        elif s['type'] == 'array' and 'enum' in s.get('items', {}):
            bad = [x for x in v if x not in s['items']['enum']]
            if bad:
                errors.append(f'{k}: {", ".join(map(str, bad))} not allowed')
    return out, errors


def parse_json(text):
    text = (text or '').strip()
    m = re.search(r'\{.*\}', text, re.S)  # a model may wrap the JSON in prose or a code fence
    try:
        return json.loads(m.group(0) if m else text)
    except ValueError:
        return None


class Usage:
    def __init__(self):
        self.input_tokens = self.output_tokens = self.searches = 0
        self.model = ''

    def cost(self, alias):
        m = CONFIG['models'].get(alias, {})
        return round((self.input_tokens * m.get('price_in', 0) + self.output_tokens * m.get('price_out', 0)) / 1e6
                     + self.searches * CONFIG['web_search']['price_per_search'], 4)


def decide(provider, alias, system, content, schema, server_tools, usage):
    """Ask the model; check and correct its answer. Returns the checked output."""
    messages = [{'role': 'user', 'content': content}]
    for attempt in range(CORRECTIONS + 1):
        text, assistant = provider.complete(alias, system, messages, schema, server_tools, usage)
        data, errors = check(parse_json(text), schema)
        if not errors:
            return data
        if attempt == CORRECTIONS:
            raise ModelError('invalid output after corrections: ' + '; '.join(errors))
        messages += [{'role': 'assistant', 'content': assistant},
                     {'role': 'user', 'content': 'Your answer did not fit the schema: ' + '; '.join(errors)
                      + '. Answer again with the JSON object only.'}]


class Claude:
    """The Claude API (the Anthropic SDK; ANTHROPIC_API_KEY). Structured output (the schema),
    adaptive thinking, the server-side fallback on a refusal, and the web tools if listed."""

    def __init__(self):
        import anthropic
        self.client = anthropic.Anthropic()

    def model_id(self, model):
        return model['id']

    def extra(self):
        return {'betas': ['server-side-fallback-2026-07-01'], 'fallbacks': 'default'}

    def complete(self, alias, system, messages, schema, server_tools, usage):
        model = CONFIG['models'][alias]
        tools = []
        if 'web_search' in server_tools:
            tools.append({'type': 'web_search_20260209', 'name': 'web_search', 'max_uses': 5})
        if 'web_fetch' in server_tools:
            tools.append({'type': 'web_fetch_20260209', 'name': 'web_fetch', 'max_uses': 5})
        messages = list(messages)
        while True:
            r = self.client.beta.messages.create(
                model=self.model_id(model), max_tokens=16000, system=system, messages=messages,
                thinking={'type': 'adaptive'},
                output_config={'effort': 'medium', 'format': {'type': 'json_schema', 'schema': schema}},
                **self.extra(), **({'tools': tools} if tools else {}))
            usage.model = r.model
            usage.input_tokens += r.usage.input_tokens + (r.usage.cache_read_input_tokens or 0)
            usage.output_tokens += r.usage.output_tokens
            stu = getattr(r.usage, 'server_tool_use', None)
            usage.searches += (getattr(stu, 'web_search_requests', 0) or 0) if stu else 0
            if r.stop_reason == 'pause_turn':  # a long server-tool turn: send it back to go on
                messages.append({'role': 'assistant', 'content': r.content})
                continue
            if r.stop_reason == 'refusal':
                raise ModelError(f'the model declined ({getattr(r.stop_details, "category", None)})')
            if r.stop_reason == 'max_tokens':
                raise ModelError('the answer was cut off (max_tokens)')
            texts = [b.text for b in r.content if b.type == 'text']
            return (texts[-1] if texts else ''), r.content


class Bedrock(Claude):
    """Claude on Amazon Bedrock (the bedrock-runtime client, through the "us." inference profiles;
    AWS credentials and AWS_REGION from the environment, e.g. an SSO profile). Not the Mantle
    client: on Kobo's AWS account Mantle serves Opus 5.5 but not Sonnet 5.5. Bedrock has neither
    the web tools nor server-side fallbacks: an Agent's web tools are left out (the run says so)
    and a refusal fails the attempt."""
    skipped_tools = ('web_search', 'web_fetch')

    def __init__(self):
        import os
        from anthropic import AnthropicBedrock
        self.client = AnthropicBedrock(aws_region=os.environ.get('AWS_REGION', 'us-east-1'))

    def model_id(self, model):
        return 'us.anthropic.' + model['id']

    def extra(self):
        return {}


class Fake:
    """For the tests: answers from markers in the record's text, no network.
      FAKE_ROUTE=<name>   choose that route (default: "ok" if there is one, else the first)
      FAKE_<FIELD>=<v>    that value for an output field
      FAKE_SLOPPY         first answer has types to coerce and an extra key, then fine
      FAKE_FIX            first answer is invalid, the correction is fine
      FAKE_INVALID        always invalid
    """
    calls = 0

    def complete(self, alias, system, messages, schema, server_tools, usage):
        Fake.calls += 1
        text = json.dumps(messages[0]['content'], ensure_ascii=False)
        corrected = len(messages) > 1
        usage.model = 'fake'
        usage.input_tokens += 100
        usage.output_tokens += 20
        if 'FAKE_INVALID' in text or ('FAKE_FIX' in text and not corrected):
            return '{"route": "no such route"}', 'invalid'
        props = schema['properties']
        m = re.search(r'FAKE_ROUTE=(\w+)', text)
        names = props['route']['enum']
        out = {'route': m.group(1) if m else ('ok' if 'ok' in names else names[0]),
               'reason': 'Fake model: chosen from the test markers.'}
        for k, s in props.items():
            if k in out:
                continue
            m = re.search(rf'FAKE_{k}=(\w+)', text)
            if s['type'] == 'array':
                out[k] = [m.group(1)] if m else []
            elif 'enum' in s:
                out[k] = m.group(1) if m else s['enum'][0]
            elif s['type'] == 'boolean':
                out[k] = False
            else:
                out[k] = f'Fake {k}.'
        if 'FAKE_SLOPPY' in text and not corrected:
            out = {**{k: (v.upper() if k == 'route' else v) for k, v in out.items()}, 'extra': 'dropped'}
            out = {k: (', '.join(v) if isinstance(v, list) else v) for k, v in out.items()}
        return json.dumps(out), json.dumps(out)


def provider(kind):
    return {'fake': Fake, 'bedrock': Bedrock}.get(kind, Claude)()

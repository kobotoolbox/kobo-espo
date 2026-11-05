"""
A real Kobo server for tests/cases/connection.py --kobo real: deploys the test forms (from
kobo/forms/*.json, through KPI's API) and makes submissions (OpenRosa XML, as Collect and
Enketo send them), on a throwaway test account's own projects only (all named
"... (espo-kobo test)"; nothing else is touched).

A production server only with KOBO_TEST_ACCOUNT_ON_PRODUCTION=yes in .env (Josh,
2026-11-05: the test account on kf.kobotoolbox.org). Deploying again updates the projects.
"""
import json
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from xml.sax.saxutils import escape

PRODUCTION = ('kf.kobotoolbox.org', 'eu.kobotoolbox.org', 'kobo.humanitarianresponse.info')


class RealKobo:
    def __init__(self, url, token, production_ok=False):
        host = urllib.parse.urlsplit(url).hostname or ''
        if not host or (not production_ok and any(host == p or host.endswith('.' + p) for p in PRODUCTION)):
            raise SystemExit(f'{url!r} is a production server: set KOBO_TEST_ACCOUNT_ON_PRODUCTION=yes '
                             'only for a throwaway test account')
        self.url, self.token = url.rstrip('/'), token
        # OpenRosa (what Collect and Enketo post to): kc.<domain>/submission; kf's old
        # /api/v1/submissions answers 410
        self.submission_url = self.url.replace('://kf.', '://kc.', 1) + '/submission'
        self.ids = {}  # uid -> (form id, version)

    def call(self, method, path, body=None, raw=None, headers=None):
        url = path if path.startswith('http') else self.url + path
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        req = urllib.request.Request(url, method=method, data=data, headers={
            'Authorization': f'Token {self.token}', 'Accept': 'application/json',
            **({'Content-Type': 'application/json'} if raw is None else {}), **(headers or {})})
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read()
            return json.loads(text) if text.strip() and r.headers.get_content_type() == 'application/json' else text

    def find(self, name):
        page = self.call('GET', '/api/v2/assets/?' + urllib.parse.urlencode(
            {'q': f'name:"{name}"', 'asset_type': 'survey', 'limit': 50}))
        return next((a for a in page['results'] if a['name'] == name), None)

    def upload(self, uid, filename, data):
        boundary = 'kobo-espo-' + uuid.uuid4().hex
        parts = [('file_type', 'form_media'), ('description', 'placeholder'),
                 ('metadata', json.dumps({'filename': filename}))]
        body = b''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                        for k, v in parts)
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="content"; filename="{filename}"\r\n'
                 'Content-Type: text/csv\r\n\r\n').encode() + data + f'\r\n--{boundary}--\r\n'.encode()
        self.call('POST', f'/api/v2/assets/{uid}/files/', raw=body,
                  headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})

    def deploy(self, content):
        name = content['settings']['form_title']
        asset = self.find(name)
        if asset is None:
            asset = self.call('POST', '/api/v2/assets/', {'name': name, 'asset_type': 'survey', 'content': content})
        else:
            asset = self.call('PATCH', f'/api/v2/assets/{asset["uid"]}/', {'content': content})
        uid = asset['uid']
        # select_one_from_file needs its file before the form works: placeholders, which
        # the bridge replaces with EspoCRM's lists
        have = {f['metadata'].get('filename') for f in self.call(
            'GET', f'/api/v2/assets/{uid}/files/?file_type=form_media')['results']}
        for row in content['survey']:
            if row['type'].startswith('select_one_from_file '):
                filename = row['type'].split(' ', 1)[1]
                if filename not in have:
                    self.upload(uid, filename, b'name,label\nplaceholder,Waiting for EspoCRM\n')
        asset = self.call('GET', f'/api/v2/assets/{uid}/')
        if asset.get('has_deployment'):
            self.call('PATCH', f'/api/v2/assets/{uid}/deployment/', {'active': True, 'version_id': asset['version_id']})
        else:
            self.call('POST', f'/api/v2/assets/{uid}/deployment/', {'active': True})
        asset = self.call('GET', f'/api/v2/assets/{uid}/')
        self.ids[uid] = (asset['content']['settings'].get('id_string') or content['settings']['form_id'],
                         asset['deployed_version_id'], asset)
        return uid

    def deploy_all(self, forms):
        return {k: self.deploy(content) for k, content in forms.items()}

    def submit(self, uid, answers, attachments=None, files=None):
        """An OpenRosa submission, with files ({filename: (bytes, mimetype)}, named by an
        answer) in the same request as Collect sends them; returns it as KPI has it.
        `attachments` (the fake Kobo's ready-made list) is ignored."""
        form_id, version, asset = self.ids[uid]
        instance = str(uuid.uuid4())
        names = {r['name']: r for r in asset['content']['survey'] if r.get('name')}
        fields = ''.join(f'<{q}>{escape(str(v))}</{q}>' for q, v in answers.items() if q in names)
        xml = (f'<?xml version="1.0"?><{form_id} id="{form_id}" version="{version}">'
               f'<formhub><uuid>{asset.get("deployment__uuid", "")}</uuid></formhub>{fields}'
               f'<__version__>{version}</__version__>'
               f'<meta><instanceID>uuid:{instance}</instanceID></meta></{form_id}>').encode()
        boundary = 'kobo-espo-' + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="xml_submission_file"; filename="s.xml"\r\n'
                'Content-Type: text/xml\r\n\r\n').encode() + xml + b'\r\n'
        for name, (data, mime) in (files or {}).items():
            body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{name}"\r\n'
                     f'Content-Type: {mime}\r\n\r\n').encode() + data + b'\r\n'
        body += f'--{boundary}--\r\n'.encode()
        self.call('POST', self.submission_url, raw=body, headers={
            'Content-Type': f'multipart/form-data; boundary={boundary}', 'X-OpenRosa-Version': '1.0',
            'Date': datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')})
        found = self.call('GET', f'/api/v2/assets/{uid}/data/?' + urllib.parse.urlencode(
            {'query': json.dumps({'_uuid': instance}), 'limit': 1}))['results']
        if not found:
            raise SystemExit(f'submission {instance} not found in {uid} after posting it')
        return found[0]

    def media_of(self, uid):
        """{filename: bytes} of the form's media, as the bridge left them."""
        out = {}
        for f in self.call('GET', f'/api/v2/assets/{uid}/files/?file_type=form_media')['results']:
            name = f['metadata'].get('filename')
            out[name] = self.call('GET', f['content']) if f.get('content') else b''
        return out

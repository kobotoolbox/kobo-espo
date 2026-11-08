#!/usr/bin/env python3
"""
The manual's pages: site/pages/<name>.html (the content) inside the shared header and
footer, written to site/<name>.html. Run after editing a page; the results are committed
and published by .github/workflows/pages.yml.

    python3 -I site/build.py

A page starts with its title and description as two HTML comments:
    <!-- title: Requests from Kobo -->
    <!-- description: ... -->
"""
import re
from pathlib import Path

SITE = Path(__file__).resolve().parent
NAV = [('index', 'Overview'), ('requests', 'Requests'), ('responses', 'Responses'),
       ('sites', 'Sites and lists'), ('projects', 'Cluster projects'),
       ('connect', 'Connecting a form'), ('running', 'Running it')]

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}: Kobo and EspoCRM</title>
<meta name="description" content="{description}">
<link rel="icon" href="static/site/icon.png" type="image/png">
<link rel="stylesheet" href="static/site/home.css">
</head>
<body>
<header class="header">
  <div class="wrap">
    <a class="header__brand" href="./"><img src="static/site/logo.svg" alt="KoboToolbox"><span class="header__product">+ EspoCRM</span></a>
    <ul class="header__nav">
{nav}
    </ul>
    <a class="button button--filled button--m" href="https://espo-test.kobolabs.dev">Open the test EspoCRM</a>
  </div>
</header>

<main>
"""

FOOT = """</main>

<footer class="footer">
  <div class="wrap">
    <div>
      <img src="static/site/logo-white.svg" alt="KoboToolbox">
      <p>Kobo and EspoCRM: request intake, response tasking and sites on one EspoCRM, connected to KoboToolbox by kobo-espo-bridge. A test, with made-up data.</p>
    </div>
    <div>
      <span class="footer__label">KoboToolbox</span>
      <ul>
        <li><a href="https://www.kobotoolbox.org">kobotoolbox.org</a></li>
        <li><a href="https://support.kobotoolbox.org">Help Center</a></li>
        <li><a href="https://docs.espocrm.com">EspoCRM documentation</a></li>
      </ul>
    </div>
    <div>
      <span class="footer__label">On this site</span>
      <ul>
{nav}
      </ul>
    </div>
  </div>
</footer>
<script src="static/site/menu.js" defer></script>
</body>
</html>
"""


def sizes(html):
    """width and height of each <img> as its file has them (screenshots are 2x: half)."""
    from PIL import Image

    def fix(m):
        path = SITE / m.group(1)
        if not path.exists():
            raise SystemExit(f'missing image: {m.group(1)}')
        w, h = Image.open(path).size
        scale = 2 if '/shots/' in m.group(1) else 1
        return f'<img src="{m.group(1)}" width="{w // scale}" height="{h // scale}"'
    return re.sub(r'<img src="(static/[^"]+)"(?: width="\d+")?(?: height="\d+")?', fix, html)


def main():
    for name, label in NAV:
        src = (SITE / 'pages' / f'{name}.html').read_text()
        title = re.search(r'<!-- title: (.*?) -->', src).group(1)
        description = re.search(r'<!-- description: (.*?) -->', src, re.S).group(1).strip()
        body = re.sub(r'<!-- (title|description): .*? -->\n?', '', src, flags=re.S)
        nav = '\n'.join(f'      <li><a href="{n if n != "index" else "./"}{".html" if n != "index" else ""}"'
                        f'{" aria-current=\"page\"" if n == name else ""}>{lab}</a></li>' for n, lab in NAV)
        html = HEAD.format(title=title, description=description, nav=nav) + sizes(body) + FOOT.format(nav=nav)
        (SITE / f'{name}.html').write_text(html)
        print(f'site/{name}.html')


if __name__ == '__main__':
    main()

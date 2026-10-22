"""Builds the site from the merged data: the page, the data of the day, and the list of every day's data.

    out/index.html              the results page (site/generate_site.py)
    out/favicon.svg             its icon
    out/data/latest.json        the merged data
    out/data/runs/<date>.json   the merged data of each day: the days already published are kept from --previous
    out/data/runs/index.html    the list of those days

Every path is relative, so the site works under any base path (it is served at /corvus-regex-ecma262-benchmarks/).
Python 3 standard library only.

Usage:
    python3 tools/build_site.py --data data/latest.json --out out [--previous <the published site>] [--date yyyy-mm-dd]
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from merge import site_links  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DAY = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--previous", help="A copy of the published site, whose data/runs are kept.")
    parser.add_argument("--date", default=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"))
    args = parser.parse_args()

    runs = os.path.join(args.out, "data", "runs")
    os.makedirs(runs, exist_ok=True)
    if args.previous:
        kept = os.path.join(args.previous, "data", "runs")
        if os.path.isdir(kept):
            for name in os.listdir(kept):
                if DAY.match(name):
                    shutil.copyfile(os.path.join(kept, name), os.path.join(runs, name))

    shutil.copyfile(args.data, os.path.join(args.out, "data", "latest.json"))
    shutil.copyfile(args.data, os.path.join(runs, f"{args.date}.json"))
    shutil.copyfile(os.path.join(ROOT, "site", "favicon.svg"), os.path.join(args.out, "favicon.svg"))
    # Data merged before the page linked this repository and the test data gains the links here, so the page has
    # them from the next push rather than the next run; the data files themselves are published as they were merged.
    with open(args.data, encoding="utf-8") as f:
        data = json.load(f)
    links = data["meta"].get("links", [])
    labels = {l.get("label") for l in links}
    data["meta"]["links"] = [l for l in site_links() if l["label"] not in labels] + links
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as page_data:
        json.dump(data, page_data)
    try:
        subprocess.run([sys.executable, os.path.join(ROOT, "site", "generate_site.py"), "--data", page_data.name,
                        "--engines", os.path.join(ROOT, "site", "engines.json"),
                        "--out", os.path.join(args.out, "index.html")], check=True)
    finally:
        os.unlink(page_data.name)

    days = sorted((m.group(1) for m in map(DAY.match, os.listdir(runs)) if m), reverse=True)
    items = "\n".join(f'<li><a href="{d}.json">{d}</a></li>' for d in days)
    with open(os.path.join(runs, "index.html"), "w", encoding="utf-8") as f:
        f.write(f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Every day's data</title>
<link rel="icon" href="../../favicon.svg">
<style>
:root {{ color-scheme: light dark; --page: #ffffff; --ink: #1d2330; --muted: #5d6676; --accent: #1c5cab; }}
@media (prefers-color-scheme: dark) {{ :root {{ --page: #0c1018; --ink: #eef1f6; --muted: #9aa3b2; --accent: #4b93ea; }} }}
body {{ margin: 0; padding: 24px 16px; background: var(--page); color: var(--ink); font: 16px/1.5 system-ui, sans-serif; }}
main {{ max-width: 720px; margin: 0 auto; }}
p {{ color: var(--muted); }}
a {{ color: var(--accent); }}
li {{ font-family: ui-monospace, monospace; }}
</style>
</head>
<body>
<main>
<h1>Every day's data</h1>
<p>The merged data of each day's build of <a href="../../">the page</a>, newest first, in the shape the page reads
(<a href="https://github.com/corvus-dotnet/corvus-regex-ecma262-benchmarks">the repository</a> documents it).
The latest is also at <a href="../latest.json">data/latest.json</a>.</p>
<ul>
{items}
</ul>
</main>
</body>
</html>
""")
    print(f"build_site: {args.out}: the page and {len(days)} day{'s' if len(days) != 1 else ''} of data")


if __name__ == "__main__":
    main()

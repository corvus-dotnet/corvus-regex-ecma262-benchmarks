"""Writes a benchmark results page: one self-contained HTML file from a data file in the shape below.

The measurements are embedded as JSON and the charts are drawn in the browser, so the page can be committed, served
from GitHub Pages or copied to a bucket as it is. The data file (JSON):

    {
      "meta": {
        "title": "...", "lede": "one paragraph under the title", "repo": "owner/name",
        "commit": "sha", "date": "ISO 8601", "runUrl": "", "runs": 0 or the runs each measurement has,
        "facts": [["Host", "..."], ["Commit", "..."]],            # shown in the run header, in order
        "links": [{"label": "...", "url": "..."}],                 # optional: related pages, in the run header
        "icon": "favicon.svg", "runner": "...", "defaultMeasure": "time",  # optional
        "method": "<p>...</p><p>...</p>",                          # the 'How to read this' section, as HTML
        "testData": {"repo": "...", "commit": "...",               # optional: the test data, and the answers it asks
                     "answers": {"utf16": n, "utf8": n},           # in each encoding (tools/answers.py), which the
                     "answersAt": {"<commit>": {"utf16": n,        # compliance figures are a share of; answersAt, the
                                                "utf8": n}}}       # same at each other commit some counts were made at
      },
      "vocab": {                                                    # the words the page uses for its two axes
        "impl": "engine", "impls": "engines", "Impls": "Engines",
        "schema": "workload", "schemas": "workloads", "Schema": "Workload", "Schemas": "Workloads",
        "failed": "failed", "centre": "Mean", "spread": "Error",
        "barLegend": "mean of the run", "whiskerLegend": "whisker: the error of the mean"
      },
      "measures": {                                                 # the figures to compare on, in order
        "time": { "label": "Time", "long": "time per operation", "parts": ["time"] },
        "allocated": { "label": "Allocated", "long": "bytes allocated", "parts": ["allocated"], "bytes": true }
      },
      "impls": [{ "id": "...", "name": "...", "group": "...", "version": "...",
                  "compliance": {"right": n, "wrong": n, "refused": n, "acceptedInvalid": n, "limited": n,
                                 "encodings": ["utf16", "utf8"], "dataCommit": "...", "note": "..."}
                                | "not ECMA-262" }],
                                                                    # compliance is optional: shown beside the name in
                                                                    # the Overall rows and the picker; its figure is the
                                                                    # right answers over meta.testData.answers of its
                                                                    # encodings; dataCommit, when the counts were made
                                                                    # at another commit of the data (checked in beside
                                                                    # a harness), makes it a share of answersAt[commit]
                                                                    # and says so; a phrase is shown as it is
      "schemas": [{ "name": "...", "note": "...", "meta": [["instances", "333"]], "url": "", "urlLabel": "" }],
      "results": { "<impl id>": { "<schema name>": null | {"limit": n} | {"wrongCount": {"counted": n, "v8": n}}
                                                 | {"error": "..."}
                                                 | { "<part>": [runs...] | {"median": n, "min": n, "max": n} } } }
    }

With --engines (a JSON file: {"engines": [{"name": "...", "impls": ["<impl id>", ...], "package": {"label": "...",
"url": "..."}, "source": "url"}]}), the page also lists each engine the data has, with the versions its rows report
and where it comes from, at its foot. An impl that no entry names is listed alone, without links, and the generator
says so.

A result of null is a failure (the implementation did not complete the schema); an absent entry was not run. A
result of {"limit": n} is a figure the harness stopped at its limit of n seconds: the page shows "> n s", the engine
did not produce a result within n seconds. {"wrongCount": {"counted": n, "v8": m}} is a count of matches that differs
from V8's, a wrong answer: the page shows "≠ count", and an engine with one is not shown as fully compliant.
{"error": "..."} is a failure with what the harness said, which the cell's tooltip shows. A
part is either every run's value, in nanoseconds (or the unit the measure says), or a summary of it. Parts of a
measure are summed, so "parse + warm" is a measure with two parts.

Usage:
    python3 generate_site.py --data results.json --out index.html [--engines engines.json] [--fragment]
"""

import argparse
import html, json
import os
import sys

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")


def engines_of(data, path):
    """The engines the data has, in the order of their first row: each entry of the file that names a row of the data,
    then each row that no entry names."""
    with open(path, encoding="utf-8") as f:
        entries = json.load(f)["engines"]
    impls = {i["id"]: i for i in data["impls"]}
    order = {i["id"]: n for n, i in enumerate(data["impls"])}
    engines, named = [], set()
    for e in entries:
        ids = [i for i in e["impls"] if i in impls]
        if not ids:
            continue
        named.update(ids)
        versions = list(dict.fromkeys(impls[i].get("version") or "" for i in ids))
        engines.append((min(order[i] for i in ids), {
            "name": e["name"], "group": impls[ids[0]].get("group", ""),
            "versions": [v for v in versions if v], "rows": [impls[i]["name"] for i in ids],
            "package": e.get("package"), "source": e.get("source"), "how": e.get("how", "")}))
    for i in data["impls"]:
        if i["id"] not in named:
            print(f"generate_site: {path} has no entry for '{i['id']}'; it is listed without links", file=sys.stderr)
            engines.append((order[i["id"]], {
                "name": i["name"], "group": i.get("group", ""), "versions": [i["version"]] if i.get("version") else [],
                "rows": [i["name"]], "package": None, "source": None, "how": ""}))
    return [e for _, e in sorted(engines, key=lambda t: t[0])]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--engines", help="Where each engine comes from, listed at the foot of the page.")
    # For hosts that supply the document skeleton themselves, such as a preview that wraps the page.
    parser.add_argument("--fragment", action="store_true", help="Emit the page without its document skeleton.")
    args = parser.parse_args()

    with open(args.data, encoding="utf-8") as f:
        data = json.load(f)
    for key in ("meta", "vocab", "measures", "impls", "schemas", "results"):
        if key not in data:
            raise SystemExit(f"the data has no '{key}'")
    if args.engines:
        data["engines"] = engines_of(data, args.engines)

    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    with open(TEMPLATE, encoding="utf-8") as f:
        page = f.read().replace("/*BENCHMARK_DATA*/null", payload)
    # The page's title is the run's, and an icon when the data names one (meta.icon, a path the host serves):
    # without a link the browser asks for /favicon.ico and logs a 404 on a host that has none.
    meta = data.get("meta", {})
    head_tags = "<title>" + html.escape(meta.get("title") or "Benchmark results") + "</title>"
    if meta.get("icon"):
        head_tags += '\n<link rel="icon" href="' + html.escape(meta["icon"], quote=True) + '">'
    page = page.replace("<title>Benchmark results</title>", head_tags, 1)
    if not args.fragment:
        head, body = page.split("<header", 1)
        page = (
            '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            f"{head}</head>\n<body>\n<header{body}</body>\n</html>\n"
        )

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(page)


if __name__ == "__main__":
    main()

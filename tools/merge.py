"""Merges the benchmark runs of every Corvus ECMA-262 regex engine into one results-page data file.

Each source in the manifest (sources.json) is an engine repository. With `--runs` (the runs.json that
tools/sources.py writes after running every source's container image on this machine), a source's data is the
file its image wrote here. A source whose image did not run tonight is shown as not run, never filled in from a run
on another machine, so every figure on the page was measured on this runner. Every file is checked
against the data shape of site/generate_site.py; a source that cannot be read or does not have the shape is reported
and skipped, never fatal, so one broken repository never takes the page down. The merged file has:

- `impls`: every source's implementations, each id prefixed with the source id (`dotnet/Corvus interpreter`) and
  `group` set to the source's language; V8 once, from the first source that has it, in the group "V8";
- `schemas`: the workloads, matched by name across sources (every source uses the Industry workload ids);
- `measures`: the union, in the order first seen; `results`: per implementation, as the source gave them;
- `meta`: the title, a lede that says where the figures were measured (here, in one job), each source's release,
  commit and run time as facts (or "not run tonight"), links to each source's repository
  and run, and `date`, the newest source's date.

Python 3 standard library only.

Usage:
    python3 tools/merge.py [--sources sources.json] [--runs out-data/runs.json] --out data/latest.json [--run-url URL]

A source's data file may also be named directly in runs.json, for trying a source before its image is published.
"""

import argparse
import datetime
import html
import json
import os
import sys
import urllib.request

TITLE = "Corvus ECMA-262 regex engines: the Industry benchmarks"
REPO = "corvus-dotnet/corvus-regex-ecma262-benchmarks"
LEDE = (
    "Every Corvus ECMA-262 regex engine, its platform's own regex engines and V8, over the Industry workloads of "
    "dotnet/performance. "
)
LEDE_HERE = "Every engine ran on this runner in this hour, in one job, so a figure compares across languages as well as within one."
DEFAULT_VOCAB = {
    "impl": "engine", "impls": "engines", "Impls": "Engines",
    "schema": "workload", "schemas": "workloads", "Schema": "Workload", "Schemas": "Workloads",
    "failed": "did not run", "centre": "Mean", "spread": "StdDev",
    "barLegend": "mean of the run", "whiskerLegend": "whisker: one standard deviation",
}


def warn(message):
    print(f"merge: {message}", file=sys.stderr)


def fetch(url):
    if "://" not in url:
        with open(url, encoding="utf-8") as f:
            return json.load(f)
    request = urllib.request.Request(url, headers={"User-Agent": REPO, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def check(data):
    """Returns why the data does not have the results-page shape, or None when it does."""
    if not isinstance(data, dict):
        return "not a JSON object"
    for key, kind in (("meta", dict), ("measures", dict), ("impls", list), ("schemas", list), ("results", dict)):
        if not isinstance(data.get(key), kind):
            return f"'{key}' is missing or not an {'object' if kind is dict else 'array'}"
    if not data["impls"]:
        return "'impls' is empty"
    ids = set()
    for impl in data["impls"]:
        if not isinstance(impl, dict) or not isinstance(impl.get("id"), str) or not impl["id"]:
            return "an implementation has no id"
        if impl["id"] in ids:
            return f"the implementation id '{impl['id']}' is repeated"
        ids.add(impl["id"])
    for schema in data["schemas"]:
        if not isinstance(schema, dict) or not isinstance(schema.get("name"), str):
            return "a workload has no name"
    for key, measure in data["measures"].items():
        if not isinstance(measure, dict) or not isinstance(measure.get("parts"), list):
            return f"the measure '{key}' has no parts"
    for impl_id, results in data["results"].items():
        if impl_id not in ids:
            return f"results name the implementation '{impl_id}', which is not in 'impls'"
        if not isinstance(results, dict):
            return f"the results of '{impl_id}' are not an object"
    return None


def is_v8(impl):
    return impl.get("group") == "V8" or str(impl.get("name") or impl["id"]).startswith("V8")


def runner_of(meta):
    if meta.get("runner"):
        return str(meta["runner"])
    for fact in meta.get("facts") or []:
        if isinstance(fact, list) and len(fact) == 2 and str(fact[0]).lower() in ("runner", "host"):
            return str(fact[1])
    return "runner not recorded"


def parse_date(value):
    try:
        if len(value) == 10:
            return datetime.datetime.fromisoformat(value + "T00:00:00+00:00")
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError):
        return None


def merge(sources, run_url="", runs=None):
    impls, schemas, measures, results = [], [], {}, {}
    schema_names = set()
    vocab, default_measure = None, None
    facts, links, methods, notes = [], [], [], []
    v8_from, v8_dropped = None, []
    dates = []
    used = 0
    here = []

    for source in sources:
        sid, language = source.get("id"), source.get("language")
        if not sid or not language:
            warn(f"a source in the manifest lacks id or language, skipped: {source}")
            notes.append(f"a manifest entry without an id or language ({html.escape(json.dumps(source))})")
            continue
        ran = (runs or {}).get("sources", {}).get(sid, {})
        data, why = None, None
        if ran.get("file"):
            try:
                data = fetch(ran["file"])
                why = check(data)
            except Exception as e:  # a file that cannot be read is treated as an image that did not run
                why = f"its data file could not be read ({e})"
            if why:
                data = None
        elif runs is not None:
            why = ran.get("error") or "it did not run here"
        if data is None:
            # Every figure on the page comes from this runner: an engine whose image did not run tonight is shown as
            # not run, never filled in from a run elsewhere.
            warn(f"{sid}: not run tonight ({why or 'no image run'})")
            facts.append([language, f"not run tonight: {why or 'its image did not run'}"])
            notes.append(f"{html.escape(language)}: not run tonight ({html.escape(why or 'its image did not run')})")
            continue
        here.append(language)
        used += 1
        meta = data["meta"]
        repo = source.get("repo") or meta.get("repo") or ""
        vocab = vocab or data.get("vocab")
        default_measure = default_measure or meta.get("defaultMeasure")

        for key, measure in data["measures"].items():
            measures.setdefault(key, measure)
        for schema in data["schemas"]:
            if schema["name"] not in schema_names:
                schema_names.add(schema["name"])
                schemas.append(schema)

        for impl in data["impls"]:
            v8 = is_v8(impl)
            if v8 and v8_from is not None:
                v8_dropped.append(language)
                continue
            merged = dict(impl)
            merged["id"] = f"{sid}/{impl['id']}"
            merged["name"] = impl.get("name") or impl["id"]
            merged["group"] = "V8" if v8 else language
            merged["source"] = sid
            if v8:
                v8_from = language
            impls.append(merged)
            results[merged["id"]] = data["results"].get(impl["id"], {})

        date = meta.get("date") or ""
        parsed = parse_date(date)
        if parsed:
            dates.append((parsed, date))
        commit = str(meta.get("commit") or "")
        when = parsed.strftime("%Y-%m-%d %H:%M UTC") if parsed and len(date) > 10 else (date or "time not recorded")
        release = f"{ran.get('image', 'image')}:{ran.get('tag', '?')}"
        started, finished = parse_date(ran.get("started")), parse_date(ran.get("finished"))
        span = f"{started:%H:%M}-{finished:%H:%M} UTC" if started and finished else when
        facts.append([language, f"{release}, commit {commit[:10] or 'not recorded'}, ran here {span}"])
        if repo:
            links.append({"label": f"{language} repository", "url": f"https://github.com/{repo}"})
        if meta.get("runUrl"):
            links.append({"label": f"{language} run", "url": meta["runUrl"]})
        if meta.get("method"):
            commit_link = f' at <a href="https://github.com/{html.escape(repo)}/commit/{html.escape(commit)}">{html.escape(commit[:10])}</a>' if repo and commit else ""
            origin = f"From the image of {html.escape(repo or sid)} ({html.escape(str(ran.get('image', '')))}:{html.escape(str(ran.get('tag', '')))}), run here"
            methods.append(f"<h3>{html.escape(language)}</h3><p><i>{origin}{commit_link}.</i></p>{meta['method']}")

    # Two implementations of one name (an engine of the same name in two languages) are told apart by the language.
    counts = {}
    for impl in impls:
        counts[impl["name"]] = counts.get(impl["name"], 0) + 1
    for impl in impls:
        if counts[impl["name"]] > 1 and impl["group"] != "V8":
            impl["name"] = f"{impl['name']} ({impl['group']})"

    lede = LEDE + (LEDE_HERE if here else "No engine ran on this runner tonight; the previous nights are in every day's data.")
    where = (
        "<p><b>Where the figures come from.</b> This repository's nightly workflow runs each engine repository's "
        "published container image, at its latest release, one after another in one job on one runner; each image "
        "runs its engines, its platform's competitors and V8 over the workloads, then the ECMA-262 test data for "
        "compliance. So the figures of every engine run here were measured on one machine in one hour.</p>"
        if here else
        "<p><b>Where the figures come from.</b> No engine's image ran tonight.</p>"
    )
    method = [
        where,
        "<p><b>Compliance</b> beside an engine's name is its result on the ECMA-262 test data, whose answers are "
        "V8's: the share of the data it answered as V8 does, right over everything judged (the counts are in its "
        "tooltip), \"the oracle\" for V8, and \"not ECMA-262\" for an engine that implements another "
        "dialect, whose figures are a reference for speed and not for answers.</p>",
    ]
    if v8_from:
        others = sorted(set(v8_dropped))
        dropped = f"; the V8 figures of the {', '.join(others)} run{'s' if len(others) > 1 else ''} are not shown" if others else ""
        method.append(f"<p><b>V8</b> appears once, from the {html.escape(v8_from)} run{html.escape(dropped)}.</p>")
    if notes:
        method.append("<p><b>Sources skipped this time:</b> " + "; ".join(notes) + ".</p>")
    method.extend(methods)

    links.append({"label": "Every day's data", "url": "data/runs/"})
    meta = {
        "title": TITLE,
        "lede": lede,
        "repo": REPO,
        "icon": "favicon.svg",
        "facts": ([["Runner", runs["machine"]]] if runs and here and runs.get("machine") else []) + facts
                 + ([["Skipped", str(len(notes))]] if notes else []),
        "links": links,
        "method": "".join(method),
    }
    if dates:
        meta["date"] = max(dates)[1]
    if run_url:
        meta["runUrl"] = run_url
    if default_measure and default_measure in measures:
        meta["defaultMeasure"] = default_measure
    return used, {
        "meta": meta,
        "vocab": vocab or DEFAULT_VOCAB,
        "measures": measures,
        "impls": impls,
        "schemas": schemas,
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sources", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sources.json"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--runs", help="The runs.json of tools/sources.py run: the data each image wrote here.")
    parser.add_argument("--run-url", default="", help="The URL of the workflow run that merges, for the page header.")
    args = parser.parse_args()

    with open(args.sources, encoding="utf-8") as f:
        sources = json.load(f)["sources"]
    runs = None
    if args.runs:
        with open(args.runs, encoding="utf-8") as f:
            runs = json.load(f)
    used, data = merge(sources, args.run_url, runs)
    if not used:
        raise SystemExit("merge: no source could be read, so there is nothing to publish")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"merge: {used} of {len(sources)} sources, {len(data['impls'])} implementations, "
          f"{len(data['schemas'])} workloads -> {args.out}")


if __name__ == "__main__":
    main()

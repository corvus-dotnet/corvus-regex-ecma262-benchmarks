"""Merges the runs of every source's image into one results-page data file.

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
    python3 tools/merge.py --restate published/latest.json --out data/latest.json
        (a published file with the page's text made again by this code, for a build with no run: see restate)

A source's data file may also be named directly in runs.json, for trying a source before its image is published.
"""

import argparse
import datetime
import html
import json
import os
import re
import sys
import urllib.request

TITLE = "Regex engines on every platform: ECMA-262 compliance and performance"
REPO = "corvus-dotnet/corvus-regex-ecma262-benchmarks"
TEST_DATA_REPO = "corvus-dotnet/ecma262-regex-test-data"


def site_links(test_data=None):
    """The page's first two links: this repository (the workloads, the tools and how a run is made) and the test data
    the compliance figures come from, at the commit the run used when it is known."""
    data_url = (f"https://github.com/{test_data['repo']}/tree/{test_data['commit']}" if test_data
                else f"https://github.com/{TEST_DATA_REPO}")
    return [{"label": "How the benchmarks run", "url": f"https://github.com/{REPO}"},
            {"label": "ECMA-262 test data", "url": data_url}]
LEDE = (
    "How closely the regular expression engines of each platform follow ECMA-262, and how fast they are. Engines that "
    "implement ECMA-262 and each platform's other regex engines appear side by side, with V8 as the common reference, "
    "judged on the ECMA-262 test data and timed over the Industry workloads of dotnet/performance. "
)
NO_ENGINE_RAN = "No engine ran on this runner tonight; the previous nights are in every day's data."
LEDE_HERE = "Every engine ran on this runner tonight, in one job, so a figure compares across languages as well as within one."
DEFAULT_VOCAB = {
    "impl": "engine", "impls": "engines", "Impls": "Engines",
    "schema": "workload", "schemas": "workloads", "Schema": "Workload", "Schemas": "Workloads",
    "failed": "failed", "centre": "Mean", "spread": "StdDev",
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


def label(impls):
    """Every row names its platform, so that a row read alone says what it is: "re (Python)", "Corvus interpreter
    (.NET)". A name that already names it (".NET interpreter", "Swift Regex", "regex (Rust)") is kept, and so is V8's,
    which is one engine on every platform; a name that ends in parentheses gains the platform inside them."""
    for impl in impls:
        group, name = impl.get("group", ""), impl.get("name", "")
        if not group or group == "V8" or re.search(r"(?<![\w.+#])" + re.escape(group) + r"(?![\w+#])", name, re.I):
            continue
        impl["name"] = f"{name[:-1]}, {group})" if name.endswith(")") else f"{name} ({group})"


def page_text(here, test_data):
    """The page's lede and the general part of its method (the "How to read this" section), the same for every engine:
    what the page shows, what a figure is, how it is measured, where it comes from, and how compliance and the
    marks in the cells read."""
    lede = LEDE + (LEDE_HERE if here else NO_ENGINE_RAN)
    what = (
        "<p><b>What this page shows.</b> The regular expression engines of each platform, side by side: engines that "
        "implement ECMA-262 (the regular expressions of JavaScript), the platform's other regex engines, which "
        "implement other dialects, and V8, the engine of Node.js and Chrome, as the common reference. Each engine is "
        "judged on the ECMA-262 test data, whose answers are V8's, and timed over the Industry workloads of "
        "dotnet/performance. An engine that does not implement ECMA-262 is there for its speed alone. How each engine "
        "is called is in the list of engines at the foot of the page.</p>"
    )
    figure = (
        "<p><b>A figure</b> is the time to count every match a global search finds over the whole text of a "
        "workload, moving on one character after an empty match as JavaScript's matchAll does, in nanoseconds per "
        "count. An ECMA-262 engine is given the workload's flags with u, and V8 the flags with g and u. An engine of "
        "another dialect is given the pattern as it is with the workload's i, m and s flags, and has no figure where "
        "the pattern does not compile.</p>"
    )
    measured = (
        "<p><b>How it is measured.</b> Every harness keeps to one protocol. The workloads run one after another, "
        "each in 3 rounds of every engine in turn, the order of the engines turned each round. Each turn is a process "
        "of its own, which warms the engine, times 7 passes of as many counts as fit in 0.7 s, and reports the median "
        "pass. An engine's figure for a workload is the median of its rounds, and its spread is the fastest and the "
        "slowest round; a figure whose spread is over 5% is listed in the facts. Work a program would do once per "
        "text, such as checking that bytes are UTF-8, is done before the timing starts.</p>"
    )
    where = (
        f"<p><b>Where the figures come from.</b> <a href=\"https://github.com/{REPO}\">This repository</a>'s nightly "
        "workflow runs each source's published container image, at its newest release, one after another in one job "
        "on one runner. Each image runs its engines and V8 over the workloads, then "
        f"<a href=\"{site_links(test_data)[1]['url']}\">the ECMA-262 test data</a> for compliance. So the figures of "
        "every engine run here were measured on one machine in one night's run. Anyone can add an engine: see "
        f"<a href=\"https://github.com/{REPO}/blob/main/docs/implementing-a-source.md\">implementing a source</a>.</p>"
        if here else
        "<p><b>Where the figures come from.</b> No engine's image ran tonight.</p>"
    )
    compliance = (
        "<p><b>Compliance</b> beside an engine's name is its result on the ECMA-262 test data: its right answers over "
        "every answer the data asks in the encodings the engine answers in, counted by the data's own rule "
        "(tools/answers.py), so that an answer its runner did not ask counts against it as a wrong one does. An engine "
        "with one encoding is a share of that encoding's answers, and says which. So is an engine that implements only "
        "some of the three grammars (u, v and the legacy one without either), and one with another version of Unicode "
        "than the data's (whose answers are V8's), which is judged by the answers of its version: the list of engines "
        "gives each engine's grammars and version. The counts are in its tooltip. Counts "
        "worked out at an earlier commit of the data (for an engine too slow to judge every night) are a share of what "
        "that commit asks, and say which commit. \"Not ECMA-262\" marks an engine that implements another dialect.</p>"
    )
    stopped = (
        "<p><b>&gt; 30 s</b> in a cell: the engine did not produce a result within 30 s. Every harness stops a "
        "figure that has not finished in 30 s and does not run it again in the workload's later rounds, so such a "
        "cell has no figure, and the engine is not ranked on that workload.</p>"
    )
    count = (
        "<p><b>&ne; count</b> in a cell: the engine's count of matches on that workload differs from V8's, which is "
        "a wrong answer. An ECMA-262 engine with one has no figure there, and is not shown as fully compliant beside "
        "its name whatever its share of the test data. An engine of another dialect keeps its figure, and the "
        "workload shows both counts. A cell marked failed says, in its tooltip, what the harness reported.</p>"
    )
    return lede, [what, figure, measured, where, compliance, stopped, count]


def merge(sources, run_url="", runs=None):
    impls, schemas, measures, results = [], [], {}, {}
    schema_names = set()
    vocab, default_measure = None, None
    facts, links, notes = [], [], []
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

    label(impls)

    lede, method = page_text(here, runs.get("testData") if runs else None)
    if v8_from:
        others = sorted(set(v8_dropped))
        dropped = f"; the V8 figures of the {', '.join(others)} run{'s' if len(others) > 1 else ''} are not shown" if others else ""
        method.append(f"<p><b>V8</b> appears once, from the {html.escape(v8_from)} run{html.escape(dropped)}.</p>")
    if notes:
        method.append("<p><b>Sources skipped this time:</b> " + "; ".join(notes) + ".</p>")
    # Each image's own method text stays in its data file; the page's text is this repository's (page_text and
    # site/engines.json), so that it reads the same for every engine.

    links = site_links(runs.get("testData") if runs else None) + links
    links.append({"label": "Every day's data", "url": "data/runs/"})
    meta = {
        "title": TITLE,
        "lede": lede,
        "repo": REPO,
        "icon": "favicon.svg",
        "facts": ([["Runner", runs["machine"]]] if runs and here and runs.get("machine") else [])
                 + ([["Test data", f"{runs['testData']['repo']} at {runs['testData']['commit'][:10]}, the same for every engine"]]
                    if runs and runs.get("testData") else []) + facts
                 + ([["Skipped", str(len(notes))]] if notes else []),
        "links": links,
        "method": "".join(method),
    }
    if runs and runs.get("testData"):
        # The pin of the test data and the answers it asks in each encoding, which the page's compliance figures use.
        meta["testData"] = runs["testData"]
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


def restate(data):
    """A published data file with the page's text made again by this code, its figures untouched: the title, the
    lede, the general method and every row's platform label. A push of this repository builds the page again from the
    published data without running an image, and this is how a change to the page's text reaches it then. The parts
    of the method that belong to the run (which run V8 came from, the sources skipped) are kept."""
    meta = data.setdefault("meta", {})
    old = meta.get("method", "")
    lede, method = page_text(NO_ENGINE_RAN not in meta.get("lede", ""), meta.get("testData"))
    kept = re.findall(r"<p><b>(?:V8</b>|Sources skipped this time:</b>).*?</p>", old, flags=re.S)
    meta["title"], meta["lede"], meta["method"] = TITLE, lede, "".join(method + kept)
    label(data.get("impls", []))
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sources", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sources.json"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--runs", help="The runs.json of tools/sources.py run: the data each image wrote here.")
    parser.add_argument("--run-url", default="", help="The URL of the workflow run that merges, for the page header.")
    parser.add_argument("--restate", help="A published data file: write it with the page's text made again (restate).")
    args = parser.parse_args()

    if args.restate:
        with open(args.restate, encoding="utf-8") as f:
            data = restate(json.load(f))
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
            f.write("\n")
        print(f"merge: {args.restate}, its text made again -> {args.out}")
        return

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

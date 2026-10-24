# Regex engines on every platform: ECMA-262 compliance and performance

One page that shows ECMA-262 regex engines side by side, with each platform's own regex engines and V8 as the common
reference: how closely each answers as V8 does over the ECMA-262 test data, and how fast each counts matches over the
Industry workloads of dotnet/performance. Anyone can add an engine; see
[implementing a source](docs/implementing-a-source.md).

The page is at **https://corvus-oss.org/corvus-regex-ecma262-benchmarks/**, rebuilt every night at 03:30 UTC. The
merged data is at `data/latest.json` beside it, and every day's data is kept under `data/runs/`, named by the day the
run measured it (a rebuild of the page after a push to this repository adds no day).

**Every engine runs here.** Figures merged from runs on different runners are not comparable, so this repository's
nightly workflow runs every engine itself: one job on one runner runs each engine repository's published container
image, one after another, so every figure on the page was measured on one machine in one night's run.

## How it works

`.github/workflows/build.yml` is one job on `ubuntu-latest` (at most 340 minutes), with no toolchain installed
beyond Python and Docker:

1. `tools/sources.py workloads` writes the Industry workloads once to `workloads.json`, with the .NET repository's
   `tools/benchmarks/v8/workloads.py` at its newest release whose image can be pulled (the list comes from one
   place; the .NET image then runs at that same release).
2. `tools/sources.py texts` downloads their texts once (dotnet/performance's gzipped files, the URLs of the .NET
   repository's `Inputs.cs`) into `~/.local/share/corvus-regex-benchmarks/`, cached between runs.
3. `tools/sources.py run` pulls each source's `image` at the tag of the repository's newest GitHub release whose
   image can be pulled, a package release or a harness release (a release whose image is not published yet gives way
   to the one before it; `latest` only for a repository with no release at all), and runs it as the image contract
   below says, into `out-data/<id>/`, one source after another.
4. `tools/merge.py` merges the data files the images wrote (implementations grouped by language, V8 once, every
   workload matched by id); `tools/build_site.py` writes the page (with `site/generate_site.py` and
   `site/template.html`) and the data of the day, and the job publishes them to this repository's `gh-pages`.

**One runner, no fallback.** Every figure on the page was measured on this repository's runner, in one job. A source
whose image cannot be pulled, fails, or writes no data file in the shape below is shown as "not run tonight", with
the reason, and its engines have no rows that night; the previous nights are in the daily data. It never stops the
other sources from being published.

## The results contract

A source's image writes one data file in the results-page shape. The
plan's wording of what a source publishes:

- `benchmarks/latest.json`: the run, in the results-page data shape (the `corvus-benchmark-results-page` skill:
  `meta`, `impls`, `schemas`, `measures`, `results`), and `benchmarks/runs/<date>-<commit>.json`, the same file
  kept per day.
- `meta` carries the repository, the commit, the run's time, the runner and the host as the harness recorded them
  (never typed in), the workflow run's URL, and the engine versions; `impls` are the engines the image measures
  (its own and the platform's others) and V8, each with its `group` (the language) and its compliance (the counts, or
  "not ECMA-262"); `schemas` are the Industry workload ids, the same names in every repository (the list comes from
  one place, `workloads.py`); `measures.time` is nanoseconds per `Count`.

The data shape itself is documented at the top of `site/generate_site.py`. In brief:

```json
{
  "meta": { "title": "...", "repo": "owner/name", "commit": "sha", "date": "ISO 8601", "runUrl": "...",
            "runner": "...", "facts": [["Host", "..."]], "method": "<p>...</p>" },
  "vocab": { "impl": "engine", "impls": "engines", "schema": "workload", "schemas": "workloads", "...": "..." },
  "measures": { "time": { "label": "Time", "long": "time per Count", "parts": ["time"] } },
  "impls": [{ "id": "Corvus interpreter", "name": "Corvus interpreter", "group": "Rust", "version": "0.1.0",
              "compliance": { "right": 1000, "wrong": 0, "refused": 0, "acceptedInvalid": 0, "limited": 0,
                              "judge": { "runner": "https://github.com/owner/name/blob/main/tools/dataset.rs",
                                         "calls": { "utf16": ["Regex::captures_utf16"], "utf8": ["Regex::captures"] } },
                              "excludes": [] } }],
  "schemas": [{ "name": "sherlock: Holmes", "note": "", "meta": [["text", "..."]] }],
  "results": { "Corvus interpreter": { "sherlock: Holmes": { "time": { "median": 1.0, "min": 0.9, "max": 1.1 } } } }
}
```

`compliance` is the engine's result on the ECMA-262 test data: an object of counts (`right`, `wrong`, `refused`,
`acceptedInvalid`, `limited`), with `judge` (the runner's address and the calls it makes in each encoding it asks in)
and `excludes` (what it leaves out, each of the five kinds that
[implementing a source](docs/implementing-a-source.md#what-a-runner-may-leave-out) allows, shown as badges); or the
string `"not ECMA-262"` for an engine of another dialect. The page shows it beside the engine's name as its right
answers over every answer the test data asks of it, which the nightly run counts from the pinned data by the data's
own rule (`tools/answers.py`, carried in `meta.testData.answers`): an answer its runner did not ask counts against it
as a wrong one does, so 100% means every answer asked and right. A compliance that gives a kind of exclusion not
allowed, or leaves out an encoding without saying so, is not shown, and the page says why. V8 has its counts like any
other engine.
The runner is read from `meta.runner`, or from a fact named `Host` or `Runner`.

How the merge treats a source's data:

- every implementation id is prefixed with the source id (`dotnet/Corvus interpreter`), so ids stay unique, and its
  `group` becomes the source's language; two engines of one name in two languages get the language after the name;
- V8 is shown once, from the first source in the manifest that has it (an implementation whose `group` is `V8` or
  whose name starts with `V8`); the page says which runs' V8 figures are not shown;
- workloads are matched by name; a workload missing from a source is missing for that source's engines;
- the page's date is the newest source's date.

## The image contract

Each engine repository publishes a container image, `ghcr.io/corvus-dotnet/corvus-regex-ecma262-<lang>`, tagged with
each release's version and `latest`, whose entry point is its benchmark harness. Run as

```sh
docker run --rm -v <workloads.json>:/workloads.json:ro -v <texts dir>:/texts:ro -v <out dir>:/out <image>
```

it runs its engines (the source's own and the platform's others) and V8 over the workloads (the texts are the gzipped files the
workloads name, in `/texts`), runs the ECMA-262 test data for each engine's compliance, and writes the data file to
`/out/industry.json`. A non-zero exit, or a file without the shape above, makes the source "not run tonight", with
the reason. The out directory is writable by any user, so the image may run as a user of its own.

Given `-e V8=0`, the image runs neither V8's timings nor V8 over the test data, and its data file has no V8 row: it
checks its engines' counts against each workload's `v8Count` (V8's count, which the nightly run writes into
`workloads.json` once, before any image runs) where it would have checked them against its own V8 run, so an
ECMA-262 engine that counts otherwise is still an error and another engine's row is still marked where its count
differs. The counts are all or none: when V8 cannot count every workload, no workload carries a count and no image is
given `V8=0`. The
page shows V8 once, so the nightly run gives `V8=0` to every source but the one `sources.json` marks `"v8": true` (the
.NET source); when that source has had its turn and given no V8 (its image failed or could not be pulled), the next
source runs without `V8=0`, and so on until one gives V8, and the page says which image timed it. An image that does
not know the variable still runs V8, whose rows the merge then leaves out.

## Adding a source

**[docs/implementing-a-source.md](docs/implementing-a-source.md)** is the guide to implementing a new source: what to
build (a data-set runner, an Industry harness, a results script, the image and its workflow), how a runner judges the
ECMA-262 test data and how the page turns its counts into a compliance figure (the rule, the encodings, ill-formed
UTF-8, checking a runner against `tools/answers.py` and the test data's fuzzer), the constraints on the benchmark (the
interleaved protocol, the 30 s limit on a figure, the count check against V8 and its CI gate, validation outside what
is timed), the data file and the image, and registering it in `sources.json` and `site/engines.json`.

## Running it locally

Python 3, standard library only, and Docker (or `CONTAINER_ENGINE=podman`). The whole run, as the workflow does it:

```sh
python3 tools/sources.py workloads --work work --workloads workloads.json
python3 tools/sources.py texts --workloads workloads.json
python3 tools/sources.py run --workloads workloads.json --out out-data
python3 tools/merge.py --runs out-data/runs.json --out data/latest.json
python3 tools/build_site.py --data data/latest.json --out out
# then open out/index.html
```

A source's `url` in a copy of the manifest may be a local path (`--sources my-sources.json`), to try a source's data
before it is published.

## Licence

Apache-2.0; see [LICENSE](LICENSE).

# Regex engines on every platform: ECMA-262 compliance and performance

Most platforms have a regular expression engine of their own, and most of the time that's fine. But a pattern doesn't
always mean the same thing in two engines. If you need the same answer everywhere (we do, because a JSON Schema
`pattern` is defined by ECMA-262, the `RegExp` of JavaScript), then "close enough" isn't good enough.

So this repository builds one page that puts the regex engines of every platform side by side. For each engine it
shows two things. First, how closely it answers as V8 does over the
[ECMA-262 test data](https://github.com/corvus-dotnet/ecma262-regex-test-data). Second, how fast it counts the matches
in the Industry workloads of [dotnet/performance](https://github.com/dotnet/performance). V8 is the common reference
throughout.

The page is at **https://corvus-oss.org/corvus-regex-ecma262-benchmarks/**.

It is rebuilt every night. (The schedule says 03:30 UTC, but GitHub usually gets round to starting it a few hours
later.) The merged data sits beside the page in `data/latest.json`, and every day's data is kept under `data/runs/`,
named for the day it was measured. Rebuilding the page after a push to this repository doesn't add a day.

There's a page for each processor architecture, chosen with the Architecture filter at the top: x86-64 at the root and
arm64 under `arm64/`, each with its own `data/latest.json` and `data/runs/`. No figure is ever compared across them.

Anyone can add an engine. See [implementing a source](docs/implementing-a-source.md).

## Why everything runs here

You can't compare figures measured on different machines. So rather than collect each engine repository's own
results, the nightly workflow here runs every engine itself. One job on an x86-64 runner, and one on an arm64 runner
alongside it, each runs every engine repository's published container image in turn. Every figure on a page was
measured on that page's machine, in the same night's run. An image with no build for the runner's architecture is shown
as not run on that architecture's page.

There's no fallback. If a source's image can't be pulled, fails, or writes a data file in the wrong shape, the page
shows that source as "not run tonight" (with the reason), and its engines have no rows that night. The previous
nights are still in the daily data, and one broken source never stops the others being published.

## What gets measured

There are two kinds of measurement on the page: compliance, and speed.

**Compliance** comes from the [ECMA-262 test data](https://github.com/corvus-dotnet/ecma262-regex-test-data). That's
V8's answers to a large set of patterns and texts, test262's patterns and `exec` calls, and a fair slug of
`replace`, `split` and global search besides. Every engine is judged on the same pinned commit of the data. There's
more on how that turns into a figure under [Compliance](#compliance) below.

**Speed** comes from the Industry workloads. These are the pattern sets of dotnet/performance's
`Perf.Regex.Industry` benchmarks, which in turn were adapted from
[mariomka/regex-benchmark](https://github.com/mariomka/regex-benchmark),
[rust-lang/regex](https://github.com/rust-lang/regex),
[rust-leipzig/regex-performance](https://github.com/rust-leipzig/regex-performance), the Boost regex documentation
and [BurntSushi/rebar](https://github.com/BurntSushi/rebar). There are 57 of them, over five texts.

| Text | Size | Workloads | What they look for |
|---|--:|--:|---|
| mariomka | 0.05 M chars | 3 | an email address, a URI and an IPv4 address |
| Sherlock Holmes | 0.6 M chars | 37 | literals, case-insensitive literals, alternations, classes, Unicode properties, anchors and the rest |
| Leipzig corpus (Mark Twain) | 16 M chars | 11 | names, alternations of names, windows around them, and a Unicode property |
| OpenSubtitles, Russian | 1.2 M chars | 4 | Cyrillic literals and alternations, with and without `i` |
| OpenSubtitles, Chinese | 0.3 M chars | 2 | a Chinese literal and an alternation of names |

Each figure is the time it takes to count every match a global search finds over the whole text. After an empty
match the search moves on one character, as JavaScript's `matchAll` does. The figure is in nanoseconds per count.
An ECMA-262 engine gets the workload's flags plus `u`, and V8 gets them plus `g` and `u`. An engine of another dialect
gets the pattern as it is, with the workload's `i`, `m` and `s` flags.

Every harness keeps to the same protocol. The workloads run one after another, each in three rounds of every engine,
and the order of the engines turns each round. Each turn is a process of its own, which warms the engine up, times
seven passes of as many counts as fit in 0.7 s, and reports the median pass. An engine's figure for a workload is the
median of its rounds, and its spread runs from the fastest round to the slowest. Anything a program would do once per
text (checking that its bytes are UTF-8, for example) is done before the timing starts. A figure that hasn't finished
in 30 s is stopped, and the cell says so.

<details>
<summary>All 57 workloads</summary>

**mariomka**

- `[\w\.+-]+@[\w\.-]+\.[\w\.-]+`
- `[\w]+://[^/\s?#]+[^\s?#]+(?:\?[^\s#]*...`
- `(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][...`

**sherlock**

- `Sherlock`
- `Holmes`
- `Sherlock Holmes`
- `Sherlock /i`
- `Holmes /i`
- `Sherlock Holmes /i`
- `Sherlock\s+Holmes`
- `Sherlock|Street`
- `Sherlock|Holmes`
- `Sherlock|Holmes|Watson|Irene|Adler|Jo...`
- `Sherlock|Holmes|Watson|Irene|Adler|Jo... /i`
- `Sher[a-z]+|Hol[a-z]+`
- `Sher[a-z]+|Hol[a-z]+ /i`
- `Sherlock|Holmes|Watson`
- `Sherlock|Holmes|Watson /i`
- `zqj`
- `aqj`
- `aei`
- `the`
- `The`
- `the /i`
- `the\s+\w+`
- `.*`
- `[^\n]*`
- `.* /s`
- `\p{L}`
- `\p{Lu}`
- `\p{Ll}`
- `\w+`
- `\w+\s+Holmes`
- `\w+\s+Holmes\s+\w+`
- `Holmes.{0,25}Watson|Watson.{0,25}Holmes`
- `^Sherlock Holmes|Sherlock Holmes$ /m`
- `\b\w+n\b`
- `[a-q][^u-z]{13}x`
- `[a-zA-Z]+ing`
- `\s[a-zA-Z]{0,12}ing\s`

**leipzig**

- `Twain`
- `Twain /i`
- `[a-z]shing`
- `Huck[a-zA-Z]+|Saw[a-zA-Z]+`
- `Tom|Sawyer|Huckleberry|Finn`
- `Tom|Sawyer|Huckleberry|Finn /i`
- `.{0,2}(Tom|Sawyer|Huckleberry|Finn)`
- `.{2,4}(Tom|Sawyer|Huckleberry|Finn)`
- `Tom.{10,25}river|river.{10,25}Tom`
- `([A-Za-z]awyer|[A-Za-z]inn)\s`
- `\p{Sm}`

**rebar-ru**

- `Шерлок Холмс`
- `Шерлок Холмс /i`
- `Шерлок Холмс|Джон Уотсон|Ирен Адлер|и...`
- `Шерлок Холмс|Джон Уотсон|Ирен Адлер|и... /i`

**rebar-zh**

- `夏洛克·福尔摩斯`
- `夏洛克·福尔摩斯|约翰华生|阿德勒|雷斯垂德|莫里亚蒂教授`

</details>

## A wrong answer is not a result

Every engine's count of matches is checked against V8's. If an engine counts something different, it has given a
wrong answer, and the page shows that as a failure (✕) with both counts in the tooltip. It doesn't matter whether the
engine claims to implement ECMA-262 or not. An engine that found no matches at all can be very quick about it, and we
don't want that time ranked alongside the engines that got the answer right.

For an engine that does claim ECMA-262, a wrong count is also one more wrong answer in the compliance figure beside its
name.

## How it works

`.github/workflows/build.yml` is a single job on `ubuntu-latest`, with a limit of 340 minutes. It installs nothing but
Python and Docker, and runs these steps.

1. `tools/sources.py workloads` writes the Industry workloads to `workloads.json`. The list comes from one place, the
   .NET repository's `tools/benchmarks/v8/workloads.py`, at that repository's newest release whose image can be
   pulled. The .NET image then runs at the same release.
2. `tools/sources.py texts` downloads the texts the workloads need (dotnet/performance's gzipped files, from the URLs
   in the .NET repository's `Inputs.cs`) into `~/.local/share/corvus-regex-benchmarks/`. They're cached between runs.
3. `tools/sources.py run` pulls each source's image and runs it, one source after another, into `out-data/<id>/`. It
   takes the image at the tag of the repository's newest GitHub release whose image can be pulled, whether that's a
   package release or a harness release. (If a release's image isn't published yet, the one before it is used, and a
   repository with no release at all gets `latest`.) The images are public, so nothing signs in to pull them.
4. `tools/merge.py` merges the data files the images wrote. Engines are grouped by language, V8 appears once, and
   workloads are matched by id. `tools/build_site.py` then writes the page (from `site/generate_site.py` and
   `site/template.html`) and the day's data, and the job publishes them to this repository's `gh-pages`.

## The results contract

Each source's image writes one data file, in the results-page shape. The shape is documented at the top of
`site/generate_site.py`, and it's also a JSON Schema (draft 2020-12),
[`schema/results.schema.json`](schema/results.schema.json), with an example file beside it. You can check a data file
against it with our own validator before you publish it.

```sh
python3 -m pip install corvus-json-schema
python3 schema/validate.py out/industry.json
```

In brief, the shape looks like this.

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

- `meta` carries the repository, the commit, the time of the run, the runner and the host, all as the harness
  recorded them (never typed in by hand), along with the workflow run's URL and the engines' versions. The page reads
  the runner from `meta.runner`, or from a fact named `Host` or `Runner`.
- `impls` are the engines the image measures (its own and the platform's others) and V8. Each has a `group` (its
  language) and a `compliance`.
- `schemas` are the Industry workload ids. They're the same names in every repository, because the list comes from
  `workloads.py`.
- `measures.time` is nanoseconds per `Count`.
- A result is a time, or one of three ways of having no time. `{"limit": n}` means no result within n seconds.
  `{"wrongCount": {"counted": n, "v8": m}}` is a count other than V8's. `{"error": "..."}` is any other failure, with
  what the harness said.

### Compliance

`compliance` is how the engine did on the ECMA-262 test data. For an engine of another dialect it's just the string
`"not ECMA-262"`. Otherwise it's an object of counts (`right`, `wrong`, `refused`, `acceptedInvalid` and `limited`),
plus `judge` and `excludes`. `judge` says where the runner lives and which calls it makes in each encoding it asks in.
`excludes` lists anything the runner leaves out, which must be one of the four kinds that
[implementing a source](docs/implementing-a-source.md#what-a-runner-may-leave-out) allows. The page shows each as a
badge.

The page shows compliance beside the engine's name, as its right answers over every answer the test data asks of it.
The nightly run counts those from the pinned data, by the data's own rule (`tools/answers.py`, carried in
`meta.testData.answers`). An answer the runner didn't ask counts against it, just as a wrong one does, so 100% really
does mean every answer was asked and every answer was right. If a compliance claims an exclusion that isn't allowed,
or quietly leaves out an encoding, the page doesn't show it, and says why. V8 has its counts like any other engine.

### How the merge treats a source's data

- Every engine id gets the source id in front of it (`dotnet/Corvus interpreter`), so ids stay unique, and its
  `group` becomes the source's language. If two engines in two languages share a name, the language goes after the
  name.
- V8 is shown once, from the first source in the manifest that has it (an engine whose `group` is `V8`, or whose name
  starts with `V8`). The page says which runs' V8 figures it left out.
- Workloads are matched by name. A workload missing from a source is missing for that source's engines.
- The page's date is the newest source's date.

## The image contract

Each engine repository publishes a container image, `ghcr.io/corvus-dotnet/corvus-regex-ecma262-<lang>`, tagged with
each release's version and with `latest`. Its entry point is the benchmark harness, and it runs like this.

```sh
docker run --rm -v <workloads.json>:/workloads.json:ro -v <texts dir>:/texts:ro -v <out dir>:/out <image>
```

The image runs its engines (its own and the platform's others) and V8 over the workloads, using the gzipped texts in
`/texts`. It runs the ECMA-262 test data for each engine's compliance, then writes its data file to
`/out/industry.json`. A non-zero exit, or a file in the wrong shape, makes the source "not run tonight", with the
reason. Any user can write to the out directory, so the image may run as a user of its own.

### `V8=0`

The page only needs V8 once, so the nightly run gives `-e V8=0` to every source except the one `sources.json` marks
`"v8": true` (the .NET source).

With `V8=0`, an image runs neither V8's timings nor V8 over the test data, and its data file has no V8 row. It checks
its engines' counts against each workload's `v8Count` instead, which the nightly run writes into `workloads.json` once,
before any image runs. So a count other than V8's is still a wrong answer, whichever engine gives it.

The counts are all or nothing. If V8 can't count every workload, no workload carries a count, and no image is given
`V8=0`. If the V8 source has had its turn and gave no V8 (its image failed, or couldn't be pulled), the next source
runs without `V8=0`, and so on until one of them gives V8. The page says which image timed it. An image that doesn't
know about the variable just runs V8 anyway, and the merge leaves those rows out.

## Adding a source

**[docs/implementing-a-source.md](docs/implementing-a-source.md)** is the guide to adding a new source. It covers:

- what to build: a data-set runner, an Industry harness, a results script, the image and its workflow
- how a runner judges the ECMA-262 test data, and how the page turns its counts into a compliance figure (the rule,
  the encodings, ill-formed UTF-8, and checking a runner against `tools/answers.py` and the test data's fuzzer)
- the rules of the benchmark: the interleaved protocol, the 30 s limit on a figure, the count check against V8 and its
  CI gate, and keeping validation out of what is timed
- the data file and the image, and registering the source in `sources.json` and `site/engines.json`

## Running it locally

You need Python 3 (the standard library is enough) and Docker, or Podman with `CONTAINER_ENGINE=podman`. This is the
whole run, as the workflow does it.

```sh
python3 tools/sources.py workloads --work work --workloads workloads.json
python3 tools/sources.py texts --workloads workloads.json
python3 tools/sources.py run --workloads workloads.json --out out-data
python3 tools/merge.py --runs out-data/runs.json --out data/latest.json
python3 tools/build_site.py --data data/latest.json --out out
# then open out/index.html; on an arm64 machine the run is arm64's, and its page goes under out/arm64:
# python3 tools/build_site.py --data data/latest.json --out out/arm64 --arch arm64 --architectures x86_64,arm64
```

To try a source's data before it's published, point its `url` at a local path in a copy of the manifest, and pass
that copy with `--sources my-sources.json`.

## Licence

Apache-2.0. See [LICENSE](LICENSE).

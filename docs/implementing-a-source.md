# Implementing a source

A source is an engine repository whose benchmark harness this site runs each night. This guide is everything a new
source has to build, and every rule its figures are held to. The .NET repository,
[corvus-dotnet/Corvus.Regex.Ecma262](https://github.com/corvus-dotnet/Corvus.Regex.Ecma262), and the Rust one,
[corvus-dotnet/corvus-regex-ecma262-rs](https://github.com/corvus-dotnet/corvus-regex-ecma262-rs), are the models;
each port's repository follows them, and copying the nearest one is the quickest start.

## What a source builds

1. **A data-set runner**: the engine over the ECMA-262 test data, judged by the data's own rule, giving the counts
   the page shows as the engine's compliance ([compliance](#compliance)).
2. **An Industry harness**: the engine, the platform's own regex engines and V8 over the Industry workloads, under
   the shared protocol ([the benchmark](#the-benchmark)).
3. **A results script**: the harness's run and the runners' counts written as one data file in the results-page
   shape ([the data file](#the-data-file)).
4. **A container image and its workflow**: the three above in one image, published to GHCR, with a smoke run and a
   count gate on every pull request ([the image](#the-image)).
5. **Two entries here**: `sources.json` and `site/engines.json` ([registering](#registering)).

The repository publishes no page and no results of its own. This site is the one page, and every figure on it is
measured on this repository's runner, in one job, so that figures compare across languages.

## Compliance

### The test data

[corvus-dotnet/ecma262-regex-test-data](https://github.com/corvus-dotnet/ecma262-regex-test-data) holds what V8 says
about some 115,000 patterns and 5.75 million texts, as JSON Lines under `data/`. Read its README, above all
"How a runner judges an engine": that section is the rule, and this guide only points at it. A runner's CI checks out
the data at a pinned commit; the image clones the data's `main` when it runs, so the page always judges at the data's
current commit.

The files a runner must handle:

- The `test` files (every `.jsonl` but the two below): each record has a pattern, flags, a validity verdict for each
  grammar (`valid.unicode`, `valid.legacy`, and `valid.unicode_sets` in the file that has it) and tests, each a text
  with a boolean answer under each grammar the pattern is valid in. `start-searches.jsonl` is one of them, built to
  find a search for where a match starts that steps past a start.
- `captures.jsonl`: the same records with, for each test and grammar, the answers of `exec`, the global search
  (`all`), the sticky flag, `replace`, `replaceAll`, `split` and `split3`.
- `ill-formed-utf8.jsonl`: texts of bytes that are not UTF-8 (`tests[].bytes`, in hexadecimal), whose right answer
  over UTF-8 is a refusal.

### How a runner judges

Each record is asked about under each grammar V8 judged it in: the record's flags with `u` added (the `unicode`
answers), its flags alone (`legacy`) and, where it has one, with `v` (`unicode_sets`).

- **Validity.** Under a grammar V8 found valid, an engine that refuses the pattern scores one *refused*; under one V8
  found invalid, one that accepts it scores one *accepted invalid*. A right verdict is not counted on its own.
- **Answers.** Each test's answer under each valid grammar is one answer over UTF-16 and, when its text holds no lone
  surrogate, one more over UTF-8. In `captures.jsonl` a test is seven answers over UTF-16 and five over UTF-8 (no
  `split` or `split3` over UTF-8); `sticky` is not asked of an empty text, nor over UTF-8 where `lastIndex` 1 falls
  between the halves of a supplementary character.
- **Ill-formed UTF-8.** Each test of `ill-formed-utf8.jsonl`, under each valid grammar, is one answer over UTF-8
  alone. The right answer is the engine's refusal of the bytes as invalid input: its defined error, never a match,
  a partial read, U+FFFD or a crash. An interface whose text type cannot hold such bytes (a Rust `&str`, a Swift
  `String`) refuses them where the bytes become that type, and that is its answer.
- **Positions and texts.** Over UTF-16, positions are code units; over UTF-8, byte offsets, and a position between
  the halves of a pair (a match without `u` can start or end there) is the third byte of the character's four. A text
  answer over UTF-8 is compared with V8's converted to UTF-8, each lone half as U+FFFD.
- **What is skipped.** A record or test marked `v8_deviation`, and nothing else.
- **No answer is a wrong answer.** A match that reaches the runner's limit (2 seconds a match in every Corvus runner),
  a crash or a hang scores one *unanswered* (`limit`) for that answer and every answer the record would have had.

An interface that cannot hold a text (an R string cannot hold a NUL; a Python `str` cannot name a position between a
pair's halves) needs a form that can, so that the runner asks every answer: the R package takes raw vectors and
`ecma_utf16` code units, the Python package `array('H')` code units. A runner that skips what its interface cannot
hold is asking less than the data asks, and its badge says so.

### What a runner prints

The last line of a runner's output is its counts, in this shape (the harness's results script reads it):

```
records 122864 (skipped 231 deviations)  right 29289554  wrong 0  refused-valid 0  accepted-invalid 0  limit 0  errors 0  in 17.1s
```

Each runner also writes the cases it got wrong, refused, accepted or ran out of time on, one to a line, to a file
its CI keeps when it fails.

### What the page shows

The results script gives each ECMA-262 engine a `compliance` object: the counts (`right`, `wrong`, `refused`,
`acceptedInvalid`, and `limited` for `limit` plus `errors`) and `encodings`, the encodings its runner answers in
(`["utf16", "utf8"]`, or one of them). The nightly run counts the answers the data asks in each encoding by the rule,
with `tools/answers.py` here, and the page shows right over every answer of the engine's encodings: an answer the
runner did not ask counts against it as a wrong one does.

- **✓ 100%** only when every answer was asked and right, and the engine's count of matches agrees with V8's on every
  workload (a count that differs is a wrong answer outside the data; see [the count check](#the-count-check)).
- An engine with one encoding says which: "100% ECMA-262 (UTF-16)".
- A runner that gives no `encodings`, or counts more answers than the data asks (it does not count by the rule), is
  shown as a share "of asked", never as fully compliant.

### Checking a runner before it is published

- `python3 tools/answers.py <data directory>` here prints the answers the data asks in each encoding, file by file.
  A runner that asks every answer gives exactly those numbers as its `right` plus `wrong` plus unanswered, file by
  file. A file whose total differs shows where the runner asks otherwise than the rule.
- `node fuzz.js <out directory> [seed] [patterns]` in the test data repository writes a fresh start-searches family,
  answered by V8, as a data directory a runner reads as it reads `data/`. Run the runner over a few seeds: a wrong
  answer is a fault in a start search, which a test of the engine's own should then keep. Any engine that does not
  try every start (a literal search, a walk back from it, a window of starts) needs this.
- Run the runner in both encodings and, for an engine with generated code or another mode, in each mode.

### Competitors

The platform's other ECMA-262 engines (QuickJS, regress, TRegex, Boost.Regex, std::regex, SRELL) are judged by the
same rule through the same runner, over the encodings each has. One with no match limit of its own is run in child
processes with a time limit for each record, and a record that makes no progress within it is counted unanswered,
every answer it would have had. That takes long (regress takes over an hour), so such an engine's counts are worked
out by hand and checked in beside the harness (`compliance-<engine>.txt`), at the data's pinned commit, and made again
when the data changes. An engine that does not claim ECMA-262 has the compliance `"not ECMA-262"`.

## The benchmark

### The workloads and the texts

The Industry workloads of dotnet/performance (`Perf.Regex.Industry`): the Sherlock Holmes, Leipzig and mariomka texts
and the rebar names, 57 of them. The list comes from one place, the .NET repository's
`tools/benchmarks/v8/workloads.py`; a source keeps a copy as `tools/benchmarks/workloads.json` for its own runs, and
the nightly run gives each image the list it made. Each workload is an `id` (the same name in every source), a
pattern, flags and a text file. The texts are dotnet/performance's gzipped files, which the run mounts at `/texts`;
the harness unzips each once, into a directory of its own, and every figure's process reads it from there.

A figure is the time of one count of every match a global search finds over the whole text, after an empty match
going on one character later, as `matchAll` does. The engines of the source and the other ECMA-262 engines run with
the workload's flags and `u`; an engine of another dialect is given the pattern as it is with the flags i, m and s
(its row is absent where the pattern does not compile); V8 runs with `gu` added.

### The protocol

Every harness follows the same protocol, stated in full in the Rust repository's
[docs/benchmarks/README.md](https://github.com/corvus-dotnet/corvus-regex-ecma262-rs/blob/main/docs/benchmarks/README.md).
The constraints a harness must keep:

- **Interleaved.** Workloads are the outer loop, each workload's rounds the next, and the engines the innermost, with
  the engine order turned by one each round: 3 rounds.
- **One process per figure.** Each turn is a child process (`<harness> --one ...`, or `node industry.mjs --one ...`
  for V8), so that one engine's caches, compiled code and heap do not reach another's figures. It warms for two
  fifths of 0.7 seconds, times 7 passes of as many counts as fit the rest, and reports their median.
- **The figure and its spread.** A workload's figure for an engine is the median of its rounds, with the fastest and
  the slowest round as its spread; a figure whose spread, (slowest - fastest) / median, is over 5% is listed in the
  run's facts and on stderr.
- **A limit of 30 s on each figure.** A figure that has not finished in 30 s is stopped, recorded as
  `{"error": "did not produce a result within 30 s", "limit": 30}`, and not run in the workload's later rounds. The
  page shows it as "> 30 s".
- **The count check.** Every engine's count is compared with V8's (see below).
- **What is timed is the engine.** The timed region is the count and nothing else. Work a program would do once per
  text, such as checking that bytes are UTF-8, is done before it: a harness checks the text once in setup and times
  the engine's member that does not check again (the C library's `_unchecked` functions, Java's `Utf8Text`, .NET's
  `...Unchecked` members). Each engine runs in its best start-up configuration, through the same public entry a
  program would use.
- **The settings.** `ROUNDS`, `SECONDS_EACH`, `PASSES` and `SPREAD` change the numbers, and the nightly run uses the
  defaults; `JOB=short` is a quick look; `CORES` pins the timed parts with taskset; `V8=0` runs no V8 (see the image).

### The count check

V8 is the oracle. A harness compares every engine's count on every workload with V8's: its own V8 run's, or with
`V8=0` the workload's `v8Count`, which the nightly run writes into the workloads once. An ECMA-262 engine whose count
differs gives no figure on that workload but the error `counted N where V8 counts M`, which the data file carries as
`{"wrongCount": {"counted": N, "v8": M}}`; the page shows it as "≠ count" and the engine loses the ✓ beside its
compliance. An engine of another dialect keeps its figure, and the workload is marked with both counts.

The data set does not hold every shape a start search can trip on, and a wrong count on a benchmark workload is how
the .NET engine's walk back from a literal was found (8,361 matches for `\b\w+n\b` over Sherlock Holmes, where V8
counts 8,366). So the harness-image workflow has a count gate: `run.sh` with `COUNT_GATE=1` counts every workload with
the source's engines beside V8, at one round of the least timing, and `count-gate.py` fails the job on any count that
is not V8's.

### The harness's output

The harness writes its run as JSON (`--out <file>`): `facts` (the host, the protocol's numbers, the versions, the
spread and count findings) and `results`, an object for each engine of an object for each workload, with `median`,
`min`, `max`, `count`, `rounds`, `spread` and `each`, or `error` (and `limit` for a figure stopped at the limit). The
results script turns it into the data file.

## The data file

The image writes one data file, `/out/industry.json`, in the results-page shape, documented at the top of
`site/generate_site.py` here:

- `meta`: the title, the repository, the commit, the date, the workflow run's URL, the runner and the host as the
  harness recorded them (never typed in), the facts, and the method (HTML: how the figures were made).
- `impls`: one for each engine. Its `id` and `name`, its `group` (the language; V8's group is `V8`), its `version` as
  the engine reports it, and its `compliance` (the object above, or `"not ECMA-262"`).
- `schemas`: one for each workload, named by its `id`, with its text in `meta`.
- `measures`: `time`, nanoseconds per count.
- `results`: for each engine and workload, `{"time": {"median": n, "min": n, "max": n}}`, or for a figure it did not
  give, `{"limit": 30}` (stopped at the limit), `{"wrongCount": {"counted": n, "v8": m}}` (a count that differs from
  V8's) or `{"error": "..."}` (any other failure, with what the harness said). Never `null` for a failure the harness
  knows the reason for: the page shows each kind as what it is.

The merge prefixes every implementation id with the source id, groups engines by language, shows V8 once, matches
workloads by name, and dates the page by its newest source.

## The image

`ghcr.io/corvus-dotnet/corvus-regex-ecma262-<lang>`, tagged with each release's version and `latest`, whose entry
point is `run.sh`. Run as

```sh
docker run --rm -v <workloads.json>:/workloads.json:ro -v <texts dir>:/texts:ro -v <out dir>:/out <image>
```

it runs the data-set runners for compliance (cloning the test data's `main` unless `/data` is mounted), then the
harness, then the results script, and writes `/out/industry.json`. A non-zero exit, or a file without the shape above,
makes the source "not run tonight" with the reason. The out directory is writable by any user, so the image may run
as a user of its own. The variables it takes:

- `V8=0`: no V8 timings and no V8 over the test data; counts are checked against each workload's `v8Count`, and the
  data file has no V8 row. The nightly run gives it to every source but the one `sources.json` marks `"v8": true`.
- `JOB=short`: the quick look, for smoke runs.
- `COUNT_GATE=1`: the count gate alone (see above), for CI.

The image carries the engine built as a program uses it, the harness, the runners and their competitors, and Node
24.22.0, the Node that wrote the test data, so that V8's answers are its own (`dataset.mjs` judges each file in a
process of its own, as the data's `verify.js` does).

The workflow (`.github/workflows/harness-image.yml`, on pull requests, on `main` and on releases):

1. Build the image.
2. Smoke-run it over two workloads with `JOB=short`, and check the data file's engines, workloads and compliance.
3. The count gate: fetch the five texts and run the image with `COUNT_GATE=1` over every workload.
4. Publish `:latest` from `main` and the version's tag from a release.

A harness change reaches the page only when it is released: the nightly run takes each source's image at the tag of
the repository's latest release.

## Registering

1. Add one entry to `sources.json` here:

   ```json
   { "id": "rust", "language": "Rust", "repo": "corvus-dotnet/corvus-regex-ecma262-rs", "image": "ghcr.io/corvus-dotnet/corvus-regex-ecma262-rs", "ref": "latest-release" }
   ```

   `id` is short and unique (it prefixes the implementation ids, and so appears in the page's address); `language` is
   the group the engines appear under; `image` is the image without a tag; `ref` is `latest-release` (the release's
   tag, else `latest`). An optional `timeoutMinutes` (default 150) bounds the run, and `"v8": true` marks the one
   source whose V8 the page shows. Two sources may come from one repository (the Rust crate and its C library are the
   sources `rust` and `c`), each with its own image.
2. Add an entry to `site/engines.json` for each engine the source measures: its name, the rows it covers
   (`<id>/<name>`), how to get it (`package`: a label and a link) and its source. The page lists them at its foot.

The engine gains its rows at the next nightly build, or from a run started by hand (`workflow_dispatch`). Before the
first one, check:

- the runner's counts, file by file, equal `tools/answers.py`'s for the encodings it declares, with none wrong;
- a few seeds of `fuzz.js` give no wrong answer;
- the harness follows the protocol above, with the 30 s limit, the count check and validation outside the timed
  region;
- the image's smoke run and count gate pass, and the data file's failures carry their kinds.

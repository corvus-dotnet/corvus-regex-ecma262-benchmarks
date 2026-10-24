# Implementing a source

This page compares ECMA-262 regular expression engines, and the regex engines each platform ships, on two things:
how closely each one answers as V8 does over a shared body of test data, and how fast it counts matches over a set of
real-world workloads. Anyone can add an engine. Each engine reaches the page through a **source**: a repository that
publishes a container image which runs the engine over the test data and the workloads and writes one data file. The
nightly build runs every source's image on the same machine, in one job, so that every figure on the page is measured
the same way and compares with every other.

This guide describes what a source builds and the rules its figures are held to. Working sources to copy from:

- [corvus-dotnet/corvus-regex-ecma262-rs](https://github.com/corvus-dotnet/corvus-regex-ecma262-rs) (Rust, with
  regex and regress beside it),
- [corvus-dotnet/Corvus.Regex.Ecma262](https://github.com/corvus-dotnet/Corvus.Regex.Ecma262) (.NET, with
  System.Text.RegularExpressions beside it),
- [corvus-dotnet/corvus-regex-ecma262-cpp](https://github.com/corvus-dotnet/corvus-regex-ecma262-cpp) (C++, with
  std::regex, Boost.Regex and SRELL beside it).

Copying the one nearest your platform is the quickest start. A source can measure several engines: the image for a
platform usually measures every engine that platform offers, so that they appear side by side.

## What a source builds

1. **A data-set runner.** It runs an engine over the ECMA-262 test data and counts its answers by the data's rule.
   These counts are the engine's compliance on the page. See [Compliance](#compliance).
2. **A benchmark harness.** It times each engine, and V8, over the workloads under the shared protocol. See
   [The benchmark](#the-benchmark).
3. **A results script.** It turns the harness's run and the runners' counts into one data file in the page's shape.
   See [The data file](#the-data-file).
4. **A container image and a workflow.** The image holds the three above. The workflow builds it, smoke-runs it and
   runs the count gate on every pull request, and publishes it. See [The image](#the-image).
5. **Two entries in this repository**, in `sources.json` and `site/engines.json`. See [Registering](#registering).

A source publishes no page and no figures of its own. This site is the only page, and every figure on it comes from
this repository's nightly run.

## Compliance

### The test data

[corvus-dotnet/ecma262-regex-test-data](https://github.com/corvus-dotnet/ecma262-regex-test-data) records what V8
answers for its patterns over their texts, as JSON Lines files under `data/` (its `manifest.json` has the counts). Its README is the
authority. Read it first, above all the section "How a runner judges an engine". This guide summarises that section
and does not replace it.

Two pins of the data matter. A runner's own CI checks out the data at a pinned commit, so its tests do not move when
the data does. The nightly build pins the data too, in this repository's `sources.json` (`testData`), and gives every
image that commit at `/data`, so that every engine on a given night is judged against the same data. The nightly pin
moves only once every source's runner reads the data at the new commit. Run by hand without `/data`, the image clones
the data's `main`.

The data has four kinds of file.

- **Test files** (every `.jsonl` file at the top of `data/` except the two below). Each record has a pattern, its flags, V8's verdict on
  whether the pattern is valid under each grammar (`valid.unicode`, `valid.legacy` and, in records that have it,
  `valid.unicode_sets`), and a list of tests. Each test is a text and, for each grammar the pattern is valid under,
  whether V8 finds a match in it.
- **`captures.jsonl`**. Records like those above, where each test also holds V8's full answers for each grammar: the
  `exec` result, every match of a global search (`all`), the sticky search (`sticky`), `replace`, `replaceAll`,
  `split` and `split3`.
- **`ill-formed-utf8.jsonl`**. Each test is a sequence of bytes that is not valid UTF-8 (`tests[].bytes`, in
  hexadecimal). The right answer is for the engine to refuse it.
- **`exec/test262.jsonl`**, in a directory of its own so that a runner that reads the top of `data/` does not take
  it for a test file. Each record is a pattern with its own flags (`g`, `y` and `d` among them) and the calls of
  `exec` that test262's tests make on it: a text, the `lastIndex` exec reads, and V8's answer (null, or the
  positions of the match and of every group, the named groups and, with `g` or `y`, the `lastIndex` exec leaves).

`start-searches.jsonl` deserves a mention. Its patterns have matches that start inside a run of the characters a
literal or a loop accepts. It catches engines that speed up their search for a match start (by searching for a
literal, walking back from one, or trying a window of starts) and skip a start they should have tried.

### How a runner judges an engine

**The grammars.** ECMA-262 reads a pattern differently depending on its flags, so each record is asked under up to
three grammars:

| Grammar | Flags the engine is given |
|---|---|
| `unicode` | the record's flags plus `u` |
| `legacy` | the record's flags as they are |
| `unicode_sets` | the record's flags plus `v` (only where the record has a `valid.unicode_sets` verdict) |

Under each grammar, the runner compiles the pattern and compares the engine's verdict with V8's.

- **Validity.** If V8 found the pattern valid and the engine refuses it, that is one *refused*. If V8 found it
  invalid and the engine accepts it, that is one *accepted invalid*. A verdict that agrees with V8's is not counted
  as an answer; it opens the record's tests under that grammar.
- **Tests.** Each test under each valid grammar is one answer over UTF-16. If the text holds no lone surrogate, it
  is one more answer over UTF-8.
- **`captures.jsonl`.** Each test under each valid grammar is seven answers over UTF-16 (`exec`, `all`, `sticky`,
  `replace`, `replaceAll`, `split`, `split3`). If the text holds no lone surrogate, it is five more over UTF-8 (the
  same, without `split` and `split3`). `sticky` is not asked of an empty text. Nor is it asked over UTF-8 when
  `lastIndex` 1 falls between the two halves of a supplementary character, because UTF-8 has no such position.
- **`exec/test262.jsonl`.** A record is asked in the one grammar its flags give (`v`, `u`, or neither: legacy), with
  its flags as they are. Each call is one answer over UTF-16. If the text holds no lone surrogate and `lastIndex` does
  not fall between the halves of a pair, it is one more over UTF-8, with positions in bytes. `lastIndex` is 0 without
  `g` or `y`, and can lie past the end of the text (as far as 2^53 - 1 and `Number.MAX_VALUE`), where exec gives null.
  An engine that refuses the pattern has one *refused*, and its calls go unanswered.
- **`ill-formed-utf8.jsonl`.** Each test under each valid grammar is one answer over UTF-8 only. The right answer
  is a refusal: the error the engine's UTF-8 interface defines for input that is not UTF-8. A match, a non-match, a
  partial read or reading the bytes as U+FFFD is wrong. A crash or a hang is unanswered. If the interface's text type
  cannot hold such bytes at all (a Rust `&str`, a Swift `String`), the refusal happens where the bytes are turned into
  that type, and that refusal is the answer.
- **Positions and texts over UTF-8.** Over UTF-16, positions are code units. Over UTF-8, they are byte offsets.
  Without `u` or `v`, a match can start or end between the two halves of a supplementary character; over UTF-8 that
  position is the third of the character's four bytes. A text in an answer (a capture, a replacement) is compared
  with V8's text converted to UTF-8, with each lone half of a pair as U+FFFD.
- **What is skipped.** Records and tests marked `v8_deviation` (the data's README lists them under "Where V8 departs
  from ECMA-262"). Nothing else, except what an engine may leave out (see
  [What a runner may leave out](#what-a-runner-may-leave-out)).
- **No answer is a wrong answer.** Every runner allows 2 seconds a match. If a match reaches that limit, or the engine
  crashes or hangs, that is one *unanswered* (`limit`), and so is every other answer that record would have given.

**Every answer must be asked.** If the engine's interface cannot hold some texts (an R string cannot hold a NUL; a
Python `str` cannot express a position between the two halves of a pair), the runner needs another form that can, so
that it still asks every answer. The R package takes raw vectors and UTF-16 code units for this, and the Python
package `array('H')` code units. A runner that skips what its interface cannot hold answers fewer questions than the
data asks, and the page shows that.

### What a runner may leave out

A runner asks every answer, with five exceptions. Each is a property of the engine, never of the runner, and each is
declared in the runner's compliance (`excludes`, below) and shown on the page as a badge of what it leaves out. The
page refuses any other kind of exclusion. Whatever else a runner does not ask counts as not answered, so a file the
runner does not read, or records it finds slow, are never left out.

| `class` | It leaves out | Allowed when | The badge |
|---|---|---|---|
| `encoding` | one encoding (`"leaves": "utf8"`, or `"utf16"`) | the engine has no interface in that encoding | no UTF-8 |
| `grammar` | one or two grammars (`"leaves": ["unicode", "unicode_sets"]`) | the engine has no such mode | no u, v |
| `unicode` | the data's answers where another version of Unicode differs (`"version": "18.0"`) | the engine's tables are of that version: its runner reads the data with that version's overlay applied (`node unicode.js apply <version> <dir>` in the test data repository) | Unicode 18.0 |
| `operations` | the engine's own global search, sticky search, replace or split (`"leaves": ["global", "replace", "split"]`, of `global`, `sticky`, `replace` and `split`) | the engine does not have them: the runner writes them over its exec, as a JavaScript engine's String methods are written | global, replace, split from exec |
| `record-limit` | any record with no answer in 30 seconds (`"seconds": 30`) | the engine cannot be stopped in a match, so it runs in child processes, and a record that makes no progress in 30 s counts as unanswered, with every answer it would have given | 30 s per record |

**Every answer must be asked.** An interface that cannot hold some texts is not an exclusion. If the engine's
interface cannot hold some texts (an R string cannot hold a NUL; a Python `str` cannot express a position between the
two halves of a pair), the runner needs another form that can, so that it still asks every answer. The R package
takes raw vectors and UTF-16 code units for this, and the Python package `array('H')` code units.

### What a runner prints

The last line of a runner's output is its counts, in this form:

```
records 123601 (skipped 232 deviations)  right 29689063  wrong 0  refused-valid 0  accepted-invalid 0  limit 0  errors 0  in 7.0s
```

A runner also writes every case it got wrong, refused, accepted or left unanswered to a file, one per line, which its
CI keeps when the run fails.

With `--compliance <file>`, a runner writes the engine's compliance object to that file, which the results script
gives the page as it is. The runner writes it, never the results script, so that what the runner leaves out and what
the page says it leaves out come from one place:

```json
{
  "right": 29689063, "wrong": 0, "refused": 0, "acceptedInvalid": 0, "limited": 0,
  "judge": {
    "runner": "https://github.com/owner/name/blob/main/tools/dataset.rs",
    "calls": { "utf16": ["Regex::is_match_utf16", "Regex::captures_utf16"], "utf8": ["Regex::is_match", "Regex::captures"] }
  },
  "excludes": []
}
```

- The counts: `right`, `wrong`, `refused`, `acceptedInvalid`, and `limited`, which is the runner's `limit` plus
  `errors`.
- `judge`: `runner`, the address of the runner's source, and `calls`, the engine's calls the runner makes in each
  encoding it asks in, by their names in the engine's own API. The page writes them as one sentence, the same for
  every engine ("Judged by dataset.rs, calling Regex::is_match_utf16 and Regex::captures_utf16 over UTF-16 and ...").
  An encoding with no calls must have an exclusion of that encoding, and one with calls must not.
- `excludes`: what the engine leaves out, each of the five kinds above, at most one of each kind. Empty for an engine
  that is asked every answer.
- `dataCommit`, for counts checked in beside the harness (see below).

The page refuses a compliance that gives anything else in place of these (a free-text note, say, or `encodings`,
`grammars` or `unicode` of its own): the engine is shown without it, and the page says why.

### What the page shows

`tools/merge.py` checks each compliance and works out what the page counts by: the encodings (those with calls),
the grammars (all but those an exclusion leaves out) and the version of Unicode (that of an exclusion of Unicode, or
the data's, V8's, from the data's `manifest.json`).

The nightly build works out how many answers the data asks in each encoding and grammar, by the rule above, with
`tools/answers.py` (and for another version of Unicode, with that version's overlay applied). An engine's figure is
its right answers over all the answers in its encodings and grammars, of its version of Unicode. An answer the runner
never asked counts against the engine exactly as a wrong answer does. The list of engines on the page gives what each
engine leaves out.

- **✓ 100%** means every answer was asked and every one was right, and the engine's match count agrees with V8's on
  every workload. (A different count is a wrong answer the data did not catch. See
  [The count check](#the-count-check).)
- Each exclusion is a badge beside the figure, for example "100% ECMA-262 · no UTF-8" or "99.88% ECMA-262 · no UTF-8 ·
  no legacy · Unicode 18.0 · global, replace, split from exec · 30 s per record". The tooltip has the counts, the
  sentence of the runner and its calls, and a sentence for each badge.
- If a runner counts more answers than the data asks (so it is not counting by the rule), the page shows its share
  "of asked" and never shows it as fully compliant.

### Checking a runner before you publish it

- Run `python3 tools/answers.py <data directory> [--unicode <version>]` in this repository. It prints how many
  answers the data asks in each encoding, in total, for each grammar and file by file (with `--unicode`, those of that
  version). A runner that asks every answer of its encodings and grammars has `right + wrong + unanswered` equal to
  those numbers in every file. A file where they differ is where the runner departs from the rule.
- Run `node fuzz.js <out directory> [seed] [patterns]` in the test data repository. It writes a fresh start-searches
  family, answered by V8, as a data directory the runner can read in place of `data/`. Run the runner over several
  seeds. A wrong answer points to a fault in the engine's search for a start, and the case belongs in the engine's own
  tests. Any engine that does not try every start one by one needs this check.
- Run the runner in both encodings and, if the engine has more than one mode (generated code, say), in every mode.

### Other engines on the platform

A source can also judge the platform's other ECMA-262 engines (for example QuickJS, regress, TRegex, Boost.Regex,
std::regex and SRELL), by the same rule and through the same runner, in whichever encodings each supports. An engine
with no match limit of its own runs in child processes with a time limit on each record. A record that makes no
progress within 30 seconds counts as unanswered, together with every answer it would have given (the `record-limit`
exclusion). Where such an engine has no global search, replace or split of its own, the runner writes them over its
exec (the `operations` exclusion), and where it has no UTF-8 interface or no mode of a grammar, it says so with the
`encoding` or `grammar` exclusion.

Such a run can take a long time (regress takes over an hour), so the image does not repeat it every night. The source
works out those counts once and checks them in beside the harness as `compliance-<engine>.json`, the runner's
`--compliance` file. Such counts are tied
to the commit of the data they were made at, and are held to three rules.

- **The file says its commit.** It gives `dataCommit`, the full commit of the test data the counts were made at.
  The commit is the full 40 characters: a prefix of the nightly pin is read as
  the pin, and any other commit that is not a full one leaves the engine's compliance off the page, with a note that
  says why (the rest of the source is shown).
- **The page judges them against that commit.** When the commit differs from the nightly pin, the nightly build counts what that commit asks with
  `tools/answers.py`, and the page shows the engine's share of those answers with "counted at the test data's
  `<commit>`". Such an engine is never shown as fully compliant, since tonight's data was not asked of it.
- **CI keeps them at its own pin.** A CI step fails when a `compliance-<engine>.json` was made at another commit than
  the one CI checks the data out at, so moving CI's pin means working the counts out again in the same change.

An engine that does not claim ECMA-262 compliance has the compliance `"not ECMA-262"`.

## The benchmark

### The workloads and the texts

The workloads are the Industry benchmarks of dotnet/performance (`Perf.Regex.Industry`): 57 patterns over five
texts. The texts are the Sherlock Holmes stories, the Leipzig corpus, mariomka's test file, and the Russian and
Chinese subtitle texts from rebar.

The list has one home, `tools/benchmarks/v8/workloads.py` in the .NET repository. A source keeps a copy as
`tools/benchmarks/workloads.json` for its own runs, and the nightly build gives each image the list it made. Each
workload is an `id` (the same in every source), a pattern, flags and a text file. The texts are dotnet/performance's
gzipped files, which the nightly build mounts at `/texts`. The harness unzips each text once, into a directory of its
own, and every timing process reads the unzipped copy.

**What is timed.** A figure is the time to count every match a global search finds over the whole text, moving on by
one character after an empty match, as `matchAll` does. It is given in nanoseconds per count.

**The flags.** ECMA-262 engines run with the workload's flags plus `u`. V8 runs with `g` and `u` added. An engine of
another dialect is given the pattern unchanged, with the workload's `i`, `m` and `s` flags; where the pattern does not
compile, that engine has no figure for the workload.

### The protocol

Every harness follows the same protocol, stated in full in the Rust repository's
[docs/benchmarks/README.md](https://github.com/corvus-dotnet/corvus-regex-ecma262-rs/blob/main/docs/benchmarks/README.md).
A harness must keep to these rules.

- **Interleaved runs.** Workloads are the outer loop, each workload's 3 rounds the next, and the engines the inner
  loop. The order of the engines turns by one each round.
- **One process per figure.** Each turn is a child process (`<harness> --one ...`, or `node industry.mjs --one ...`
  for V8), so that one engine's caches, compiled code and heap cannot affect another's figures. The process warms up
  for two fifths of 0.7 seconds, then times 7 passes, each of as many counts as fit in the rest of the 0.7 seconds,
  and reports the median pass.
- **The figure and its spread.** An engine's figure for a workload is the median of its 3 rounds, with the fastest
  and slowest rounds as its spread. If (slowest - fastest) / median is over 5%, the figure is listed in the run's
  facts and on stderr.
- **A 30 s limit on each figure.** A figure that has not finished in 30 s is stopped and recorded as
  `{"error": "did not produce a result within 30 s", "limit": 30}`. It is not run again in that workload's later
  rounds. The page shows it as "> 30 s".
- **The count check.** Every engine's count is compared with V8's. See below.
- **Only the engine is timed.** The timed region is the count and nothing else. Work a program would do once per
  text, such as checking that its bytes are valid UTF-8, happens before timing starts. The harness validates the text
  once during setup, then times the engine's entry point that does not validate again (the C library's `_unchecked`
  functions, Java's `Utf8Text`, the .NET `...Unchecked` members).
- **The engine as a program would use it.** Each engine runs in its best start-up configuration, through the public
  entry point a program would call.
- **The settings.** `ROUNDS`, `SECONDS_EACH`, `PASSES` and `SPREAD` change the protocol's numbers; the nightly build
  uses the defaults. `JOB=short` gives a quick look. `CORES` pins the timed processes with taskset. `V8=0` skips V8
  (see [The image](#the-image)).

### The count check

V8 is the reference. The harness compares every engine's count on every workload with V8's count. That is either from
the harness's own V8 run or, with `V8=0`, the workload's `v8Count`, which the nightly build works out once and writes
into the workloads. The nightly build writes a count into every workload or into none, and gives no image `V8=0`
without them, so a harness given `V8=0` always has a count to check against.

If an ECMA-262 engine's count differs, it gets no figure on that workload. Instead it gets the error
`counted N where V8 counts M`, which the data file carries as `{"wrongCount": {"counted": N, "v8": M}}`. The page shows
"≠ count" in that cell and removes the ✓ from the engine's compliance. An engine of another dialect keeps its figure,
and the workload is marked with both counts.

The test data cannot hold every shape a search for a start can get wrong. A wrong count on a workload is how one such
fault was found: an engine counted 8,361 matches of `\b\w+n\b` over the Sherlock Holmes text, where V8 counts 8,366,
while scoring 100% on the data. So the image workflow has a **count gate**. `run.sh` with `COUNT_GATE=1` counts every
workload with the source's engines and V8, using one round of the shortest timing, and `count-gate.py` fails the job
on any count that is not V8's.

### The harness's output

The harness writes its run as JSON (`--out <file>`). It has `facts` (the host, the protocol's numbers, the versions,
and the spread and count findings) and `results`: for each engine, for each workload, an object with `median`, `min`,
`max`, `count`, `rounds`, `spread` and `each`. A figure that failed has `error` in place of the timings, and `limit` as
well if it was stopped at the limit. The results script turns this into the data file.

## The data file

The image writes one data file, `/out/industry.json`, in the page's shape, which is documented at the top of
`site/generate_site.py` in this repository.

- `meta`: the title, the repository, the commit, the date (ISO 8601 with its zone, such as
  `2026-10-24T05:00:00Z`), the workflow run's URL, the runner and the host as the
  harness recorded them (never typed in by hand), the facts, and `method`, an HTML description of how the figures were
  made. The method stays in the data for anyone reading it; the page itself does not show it, nor the file's
  `vocab` (the page's words for its axes and the spread of a figure are this repository's). The page's text is this
  repository's, so that it reads the same for every engine: the general text in `tools/merge.py` and each engine's
  `how` in `site/engines.json` (see [Registering](#registering)).
- `impls`: one entry per engine, with its `id`, its `name`, its `group` (the language; V8's group is `V8`), its
  `version` as the engine reports it, and its `compliance` (the object above, or `"not ECMA-262"`). The id, the name
  and the version are strings.
- `schemas`: one entry per workload, named by its `id`, with its text in `meta`.
- `measures`: `time`, in nanoseconds per count.
- `results`: for each engine and workload, `{"time": {"median": n, "min": n, "max": n}}`. A figure that failed has
  one of these in its place, so that the page can say why:

  | Failure | Value |
  |---|---|
  | stopped at the 30 s limit | `{"limit": 30}` |
  | a count that differs from V8's | `{"wrongCount": {"counted": n, "v8": m}}` |
  | anything else | `{"error": "<what the harness said>"}` |

  Never use `null` for a failure whose reason the harness knows.

A file whose parts, ids, names, versions, compliance or date are not of these kinds is not merged: the source is
shown as not run that night, with the reason. When the nightly build merges the sources, it prefixes every engine id
with the source id, groups engines by language, shows V8 once, matches workloads by name, and dates the page by its
newest source.

## The image

The image is public, tagged with each release's version and with `latest`, and its entry point is `run.sh`. It runs as

```sh
docker run --rm -v <workloads.json>:/workloads.json:ro -v <texts dir>:/texts:ro -v <out dir>:/out <image>
```

It runs the data-set runners (cloning the test data's `main`, unless a data directory is mounted at `/data`), then
the harness, then the results script, and writes `/out/industry.json`. If it exits with a non-zero code, or writes a
file without the shape above, the page lists the source as not run that night, with the reason. The out directory is
writable by any user, so the image may run as a user of its own.

It takes these variables:

- `V8=0`: no V8 timings and no V8 run over the test data. Counts are checked against each workload's `v8Count`, and
  the data file has no V8 row. The nightly build sets it for every source except the one `sources.json` marks
  `"v8": true`, and, on a night that source gives no V8, for every source but the next, which times V8 in its place.
  So every image must still be able to time V8 and run it over the test data when the variable is absent.
- `JOB=short`: the quick look, for smoke runs.
- `COUNT_GATE=1`: the count gate alone (see above), for CI.

The image holds each engine built as a program would use it, the harness, the runners, and Node 24.22.0. That is the
Node version that wrote the test data, so the image's V8 answers are the data's own. (`dataset.mjs` judges each file in
a process of its own, as the data's `verify.js` does.)

The workflow (`.github/workflows/harness-image.yml`) runs on pull requests, on `main` and on releases:

1. Build the image.
2. Smoke-run it over two workloads with `JOB=short`, and check the data file's engines, workloads and compliance.
3. Run the count gate: fetch the five texts and run the image with `COUNT_GATE=1` over every workload.
4. Publish `:latest` from `main`, and the release's tag from a release.

### Releases

A change to a harness reaches the page only once it is released, because the nightly build takes each source's image
at the tag of its repository's newest GitHub release whose image is published. There are two kinds of release.

- **A package release** (`v<version>`, or the version alone where the package manager reads tags that way) publishes
  the engine or binding to its package registry and the harness image. Every package publish workflow checks that the
  tag names the package's version, and does nothing for a version the registry already has (or, for archives
  attached to a release, a release that already has them), so that re-running a release never fails or replaces what
  was published.
- **A harness release** (`harness-<package version>.<n>`, for example `harness-0.2.1.1`) publishes the harness image
  alone, for a change that touches only the harness side: the harness, its Dockerfile, a runner, or another engine's
  checked-in counts. It is made with `gh release create harness-0.2.1.1 --latest=false`, so that the repository's
  Latest stays the package's. Every package publish workflow skips a tag that starts `harness-`.

## Registering

1. Add an entry to `sources.json` in this repository:

   ```json
   { "id": "rust", "language": "Rust", "repo": "corvus-dotnet/corvus-regex-ecma262-rs", "image": "ghcr.io/corvus-dotnet/corvus-regex-ecma262-rs", "ref": "latest-release" }
   ```

   - `id` is short and unique. It prefixes the source's engine ids, so it appears in the page's links.
   - `language` is the group the engines appear under.
   - `repo` is the GitHub repository whose releases tag the image.
   - `image` is the image without a tag.
   - `ref` is `latest-release`: the tag of the repository's newest release of either kind whose image can be
     pulled (a release whose image is not published yet gives way to the one before it), or `latest` if the
     repository has no release at all.
   - `timeoutMinutes` (optional, default 150) bounds the source's pull and run together. A container still running
     then is killed and removed, and the source is shown as not run that night.
   - `"v8": true` marks the one source that times V8 each night, whose V8 figures the page shows. On a night it
     gives none, the next source in the list times V8 instead, and the page says so.

   One repository can provide two sources, each with its own image. The Rust crate and its C library are the sources
   `rust` and `c`.
2. Add an entry to `site/engines.json` for each engine the source measures: its name, the result rows it covers
   (`<id>/<name>`), where to get it (`package`, a label and a link), its source code (a link), and `how`, one or two
   sentences on how the harness calls it: the interface, the encodings, the flags and how matches are counted, written
   as every other entry is (for example "Python's re, with the pattern as it is and the workload's i, m and s flags,
   its matches counted with finditer."). The page lists these at its foot. Each row's name gains its platform on the
   page ("re (Python)") unless the name already says it.

The engines appear at the next nightly build, or at a run started by hand (`workflow_dispatch`). Before then, check:

- the runner's counts, file by file, equal `tools/answers.py`'s for the encodings it declares, with none wrong;
- a few seeds of `fuzz.js` give no wrong answers;
- the harness keeps to the protocol, including the 30 s limit, the count check and validation outside the timed
  region;
- the image's smoke run and count gate pass, and failures in the data file say what kind they are;
- each checked-in `compliance-<engine>.json` gives the data commit it was made at, the commit CI pins.

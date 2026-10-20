# Corvus ECMA-262 regex engine benchmarks

One page that shows the benchmark runs of every Corvus ECMA-262 regex engine side by side, with each platform's own
regex engines and V8 as the common reference, over the Industry workloads of dotnet/performance.

The page is at **https://corvus-oss.org/corvus-regex-ecma262-benchmarks/**, rebuilt every night at 03:30 UTC. The
merged data is at `data/latest.json` beside it, and every day's data is kept under `data/runs/`.

**Every engine runs here.** Figures merged from runs on different runners are not comparable, so this repository's
nightly workflow runs every engine itself: one job on one runner runs each engine repository's published container
image, one after another, so every figure on the page was measured on one machine in one hour.

## How it works

`.github/workflows/build.yml` is one job on `ubuntu-latest` (at most 340 minutes), with no toolchain installed
beyond Python and Docker:

1. `tools/sources.py workloads` writes the Industry workloads once to `workloads.json`, with the .NET repository's
   `tools/benchmarks/v8/workloads.py` at its latest release (the list comes from one place).
2. `tools/sources.py texts` downloads their texts once (dotnet/performance's gzipped files, the URLs of the .NET
   repository's `Inputs.cs`) into `~/.local/share/corvus-regex-benchmarks/`, cached between runs.
3. `tools/sources.py run` pulls each source's `image` at the tag of the repository's latest GitHub release (or
   `latest` when there is no release or that tag cannot be pulled) and runs it as the image contract below says,
   into `out-data/<id>/`, one source after another.
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
  (never typed in), the workflow run's URL, and the engine versions; `impls` are the repository's engines, the
  platform's competitors and V8, each with its `group` (the language) and its compliance (the counts, or
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
              "compliance": { "right": 22895231, "wrong": 0, "refused": 0, "acceptedInvalid": 0 } }],
  "schemas": [{ "name": "sherlock: Holmes", "note": "", "meta": [["text", "..."]] }],
  "results": { "Corvus interpreter": { "sherlock: Holmes": { "time": { "median": 1.0, "min": 0.9, "max": 1.1 } } } }
}
```

`compliance` is the engine's result on the ECMA-262 test data: an object of counts, the string `"not ECMA-262"` for
an engine of another dialect, or `"the oracle of the test data"` for V8. The page shows it beside the engine's name.
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

it runs its engines, its platform's competitors and V8 over the workloads (the texts are the gzipped files the
workloads name, in `/texts`), runs the ECMA-262 test data for each engine's compliance, and writes the data file to
`/out/industry.json`. A non-zero exit, or a file without the shape above, makes the source fall back to its
published run. The out directory is writable by any user, so the image may run as a user of its own.

## Registering a source

1. In the engine repository, publish the image above (`:latest` from main, and the version tag from each release),
   with a smoke run of it in the same workflow. The engine repository publishes no page and no results of its own:
   this site is the one page. The .NET repository is the model: `.github/workflows/harness-image.yml` in
   [corvus-dotnet/Corvus.Regex.Ecma262](https://github.com/corvus-dotnet/Corvus.Regex.Ecma262).
2. Add one entry to `sources.json` here:

   ```json
   { "id": "rust", "language": "Rust", "repo": "corvus-dotnet/corvus-regex-ecma262-rs", "image": "ghcr.io/corvus-dotnet/corvus-regex-ecma262-rs", "ref": "latest-release" }
   ```

   `id` is short and unique (it prefixes the implementation ids, and so appears in the page's address);
   `language` is the group the engines appear under; `image` is the image without
   a tag; `ref` is `latest-release` (the release's tag, else `latest`), the only policy so far. An optional
   `timeoutMinutes` (default 150) bounds the run.

The engine gains its rows on the page at the next nightly build, or straight away from a push to `main` here.

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

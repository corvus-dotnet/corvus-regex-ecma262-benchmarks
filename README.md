# Corvus ECMA-262 regex engine benchmarks

One page that shows the benchmark runs of every Corvus ECMA-262 regex engine side by side, with each platform's own
regex engines and V8 as the common reference, over the Industry workloads of dotnet/performance.

The page is at **https://corvus-oss.org/corvus-regex-ecma262-benchmarks/**, rebuilt every day at 03:30 UTC, after
the engines' nightly runs. The merged data is at `data/latest.json` beside it, and every day's data is kept under
`data/runs/`.

**A caveat on reading it.** The runs come from different runners on different nights, so a figure across languages
is a guide and a figure within a language is a measurement. Each engine repository runs its engines, its platform's
competitors and V8 on one runner in one job, so the figures of one source compare with each other; the figures of two
sources were measured on two machines.

## How it works

An engine repository is not responsible for a benchmark site. Its nightly benchmarks workflow runs its engines and
its platform's competitors on one runner, and publishes the run as data, nothing else, to its own `gh-pages`. This
repository's daily workflow (`.github/workflows/build.yml`) fetches every source listed in `sources.json`, merges
them into one data file (`tools/merge.py`: implementations grouped by language, V8 once, every workload matched by
id), writes the page with each source's commit, time and runner in the header (`tools/build_site.py`, which uses
`site/generate_site.py` and `site/template.html`), and publishes it to this repository's `gh-pages`. A source that
cannot be fetched, or whose data does not have the shape below, is reported in the log and on the page and skipped;
it never stops the others from being published.

## The results contract

What a source publishes:

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

## Registering a source

1. In the engine repository, publish `benchmarks/latest.json` in the shape above to its `gh-pages` branch, from its
   nightly benchmarks workflow. The .NET repository is the model: `.github/workflows/benchmarks.yml` and
   `.github/scripts/Update-GhPages.ps1` in
   [corvus-dotnet/Corvus.Regex.Ecma262](https://github.com/corvus-dotnet/Corvus.Regex.Ecma262).
2. Add one entry to `sources.json` here:

   ```json
   { "id": "rs", "language": "Rust", "url": "https://raw.githubusercontent.com/corvus-dotnet/corvus-regex-ecma262-rs/gh-pages/benchmarks/latest.json", "repo": "corvus-dotnet/corvus-regex-ecma262-rs" }
   ```

   `id` is short and unique (it prefixes the implementation ids, and so appears in the page's address); `language`
   is the group the engines appear under.

The engine gains its rows on the page at the next daily build, or straight away from a push to `main` here.

## Running it locally

Python 3, standard library only:

```sh
python3 tools/merge.py --out data/latest.json
python3 tools/build_site.py --data data/latest.json --out out
# then open out/index.html
```

A source's `url` in a copy of the manifest may be a local path (`--sources my-sources.json`), to try a source's data
before it is published.

## Licence

Apache-2.0; see [LICENSE](LICENSE).

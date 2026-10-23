"""Runs every engine of the manifest on this machine, each from its repository's published container image.

    python3 tools/sources.py workloads [--sources sources.json] --work work --workloads workloads.json
        Clones the .NET source at its latest release into work/dotnet and writes the Industry workloads with its
        tools/benchmarks/v8/workloads.py: the list comes from one place.

    python3 tools/sources.py texts --workloads workloads.json --texts DIR
        Downloads each text the workloads name (the Industry texts of dotnet/performance, gzipped, kept as they are)
        into DIR, unless it is there already.

    python3 tools/sources.py data [--sources sources.json] --data DIR
        Fetches the ECMA-262 test data at the commit sources.json pins ("testData") into DIR, whose data/ directory
        every image is then given: every engine of a night is judged on the same data, and a change to the data
        reaches the page when the pin is moved, once every engine's runner reads it.

    python3 tools/sources.py counts [--work DIR] --workloads workloads.json --texts DIR
        Counts each workload under V8 once, with the industry.mjs of the .NET repository the workloads came from (in
        DIR, as the workloads command left it), and writes each count into workloads.json as "v8Count". An image run
        with V8=0 checks its engines' counts against these instead of timing V8 itself; a workload V8 cannot count
        has none, and is not checked.

    python3 tools/sources.py run --workloads workloads.json --texts DIR [--data DIR/data] [--budget-minutes N] --out out-data
        For each source: pulls `<image>:<tag>`, the tag of the repository's newest GitHub release, a package release or
        a harness release (or `latest` when there is no release or that tag cannot be pulled), and runs it as the
        contract says,

            docker run --rm [-e V8=0] -v <workloads.json>:/workloads.json:ro -v <texts dir>:/texts:ro [-v <data>:/data:ro] -v <out>/<id>:/out <image>

        which writes /out/industry.json. When the workloads carry V8's counts (the counts command), every source but
        the one sources.json marks "v8": true runs with V8=0, so that V8 is timed (and run over the data) once a
        night rather than in every image: the page shows it once. Writes out-data/runs.json, after each source, so that a run cut short still
        has the sources it ran: per source, the data file (when it has the results-page shape), the image and tag
        that ran, the image's digest, the time it ran, and this machine's description. An image that cannot be
        pulled, fails or writes no usable file is recorded as such; tools/merge.py then shows the source as not run
        tonight. With --budget-minutes, no source runs past that many minutes from the start: each is given the less
        of its own limit and the time left, and one that would start with none left is recorded as not run. Counts a
        source made at another commit of the data (an engine's compliance with a dataCommit), or for another version
        of Unicode (one with a unicode), are judged against what was asked of them: the answers of each such commit
        and version are counted into runs.json's testData.answersAt.

Python 3 standard library only. GITHUB_TOKEN, when set, authenticates the GitHub API calls.
"""

import argparse
import datetime
import json
import os
import platform
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from merge import check, normalise_compliance, unicode_version  # noqa: E402

# The container engine: docker on the runner; CONTAINER_ENGINE=podman for a local run on a machine without docker.
ENGINE = os.environ.get("CONTAINER_ENGINE", "docker")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TEXTS = "https://raw.githubusercontent.com/dotnet/performance/main/src/benchmarks/micro/libraries/System.Text.RegularExpressions/TestData/"


def log(message):
    print(f"sources: {message}", flush=True)


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_sources(path):
    with open(path, encoding="utf-8") as f:
        return [s for s in json.load(f)["sources"] if s.get("id") and s.get("repo")]


def api(path):
    request = urllib.request.Request("https://api.github.com/" + path, headers={"Accept": "application/vnd.github+json", "User-Agent": "corvus-regex-ecma262-benchmarks"})
    if os.environ.get("GITHUB_TOKEN"):
        request.add_header("Authorization", "Bearer " + os.environ["GITHUB_TOKEN"])
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def latest_release(repo):
    """The tag of the repository's newest published release of either kind: a package release, or a harness release
    (a tag starting harness-), which publishes the harness image alone when only the harness changed. GitHub's "latest"
    is not used: a harness release is marked not latest, so that the repository's Latest stays its package's."""
    try:
        releases = [r for r in api(f"repos/{repo}/releases?per_page=30") if not r.get("draft") and not r.get("prerelease")]
    except Exception as e:  # the API refused: the image's latest tag is used
        log(f"{repo}: its releases could not be read ({e})")
        return None
    if not releases:  # no release yet: the image's latest tag is used
        log(f"{repo}: no release yet")
        return None
    return max(releases, key=lambda r: r.get("published_at") or "")["tag_name"]


def workloads(args):
    source = next((s for s in load_sources(args.sources) if s.get("language") == ".NET"), None)
    if source is None:
        raise SystemExit("sources: the manifest has no .NET source, whose workloads.py writes the workloads")
    tag = latest_release(source["repo"])
    path = os.path.abspath(os.path.join(args.work, source["id"]))
    command = ["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1"]
    subprocess.run(command + (["--branch", tag] if tag else []) + [f"https://github.com/{source['repo']}.git", path], check=True)
    log(f"workloads from {source['repo']} at {tag or 'its default branch'}")
    with open(args.out, "w", encoding="utf-8") as f:
        subprocess.run([sys.executable, os.path.join(path, "tools", "benchmarks", "v8", "workloads.py"),
                        os.path.join(path, "Solutions", "Corvus.Regex.Ecma262.Benchmarks", "Industry.cs")], check=True, stdout=f)
    with open(args.out, encoding="utf-8") as f:
        log(f"{len(json.load(f))} workloads -> {args.out}")


def texts(args):
    with open(args.workloads, encoding="utf-8") as f:
        files = sorted({w["file"] for w in json.load(f)})
    os.makedirs(args.texts, exist_ok=True)
    for name in files:
        path = os.path.join(args.texts, name)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            log(f"{name}: cached")
            continue
        with urllib.request.urlopen(TEXTS + name, timeout=300) as response:
            data = response.read()
        with open(path + ".part", "wb") as f:
            f.write(data)
        os.replace(path + ".part", path)
        log(f"{name}: downloaded, {len(data):,} bytes")


def describe_machine():
    cpu = ""
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            cpu = next((line.split(":", 1)[1].strip() for line in f if line.startswith("model name")), "")
    except OSError:
        pass
    image = " ".join(filter(None, [os.environ.get("ImageOS"), os.environ.get("ImageVersion")]))
    hosted = "GitHub-hosted " if os.environ.get("GITHUB_ACTIONS") else ""
    bits = [f"{hosted}{image or platform.platform()}", cpu, f"{os.cpu_count()} cores"]
    return ", ".join(b for b in bits if b)


def docker(*arguments, timeout=None):
    try:
        return subprocess.run([ENGINE, *arguments], timeout=timeout).returncode
    except FileNotFoundError:
        log(f"{ENGINE} is not installed")
        return 127


def pull(image, tag):
    """Pulls image:tag, or image:latest when that fails; returns the tag pulled, or None."""
    for candidate in [t for t in (tag, "latest") if t] if tag != "latest" else ["latest"]:
        if docker("pull", "--quiet", f"{image}:{candidate}") == 0:
            return candidate
        log(f"{image}:{candidate} could not be pulled")
    return None


def test_data(path):
    """The pin of the test data in sources.json: {"repo", "commit"}, or None."""
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("testData")


def fetch_data(repo, commit, target):
    """The test data of repo at commit, fetched into target (whose data/ directory holds the files)."""
    os.makedirs(target, exist_ok=True)
    for step in (["init", "--quiet"], ["remote", "add", "origin", f"https://github.com/{repo}"],
                 ["fetch", "--quiet", "--depth", "1", "origin", commit], ["checkout", "--quiet", "FETCH_HEAD"]):
        subprocess.run(["git", "-C", target, *step], check=True)
    log(f"test data: {repo} at {commit[:10]} -> {target}")


def data(args):
    pin = test_data(args.sources)
    if not pin:
        raise SystemExit("sources.json pins no test data (testData)")
    fetch_data(pin["repo"], pin["commit"], os.path.abspath(args.data))


def asked(path, pin, unicode):
    """The questions a source's engines were asked, other than the night's: each (commit, Unicode version) of an
    engine's compliance, its dataCommit (counts checked in beside a harness, for an engine too slow to judge every
    night) or the pin, and its unicode (an engine with another version of the Unicode Character Database than V8's)
    or the data's own."""
    try:
        with open(path, encoding="utf-8") as f:
            impls = json.load(f).get("impls", [])
    except (OSError, ValueError, AttributeError):
        return set()
    out = set()
    for i in impls:
        try:
            # As merge.py writes it on the page (a version "major.minor", a prefix of the pin as the pin), so that the
            # page finds the answers counted here.
            c = normalise_compliance(i.get("compliance"), pin["commit"]) if isinstance(i, dict) else None
        except ValueError:
            continue  # the page does not show this compliance
        if isinstance(c, dict):
            pair = (c.get("dataCommit") or pin["commit"], c.get("unicode") or unicode)
            if pair != (pin["commit"], unicode):
                out.add(pair)
    return out


def answers_at(runs, pin, work, data_dir):
    """The answers asked in each encoding and grammar for every (commit, Unicode version) a source's counts were made
    at other than the night's, into runs["testData"]["answersAt"] keyed "<commit>|<version>", so that the page judges
    such counts against what was asked of them."""
    import answers
    unicode = runs["testData"].get("unicode")
    found = {}
    for record in runs["sources"].values():
        for commit, version in asked(record.get("file"), pin, unicode) if record.get("file") else ():
            key = f"{commit}|{version}"
            if key in found:
                continue
            try:
                directory = data_dir
                if commit != pin["commit"]:
                    target = os.path.join(work, "test-data-" + commit[:12])
                    if not os.path.isdir(os.path.join(target, "data")):
                        fetch_data(pin["repo"], commit, target)
                    directory = os.path.join(target, "data")
                found[key] = {k: v for k, v in answers.count(directory, None if version == unicode else version).items()
                              if k != "files"}
            except Exception as e:  # the page then shows those counts as a share of what their runner asked
                log(f"test data at {commit[:10]}, Unicode {version}: its answers could not be counted ({e})")
    if found:
        runs["testData"]["answersAt"] = found


def counts(args):
    source = next((s for s in load_sources(args.sources) if s.get("language") == ".NET"), None)
    if source is None:
        raise SystemExit("sources: the manifest has no .NET source, whose industry.mjs counts the workloads")
    script = os.path.join(os.path.abspath(args.work), source["id"], "tools", "benchmarks", "v8", "industry.mjs")
    path = os.path.abspath(args.workloads)
    with open(path, encoding="utf-8") as f:
        all_workloads = json.load(f)
    env = dict(os.environ, CORVUS_REGEX_TEXTS=os.path.abspath(args.texts))
    counted = 0
    for k, w in enumerate(all_workloads):
        # One turn of the interleaved run, as each image's harness starts it, timed as briefly as it allows: its count.
        out = subprocess.run(["node", script, "--one", path, str(k), "0.001", "1"], capture_output=True, text=True,
                             env=env, timeout=600)
        lines = out.stdout.strip().splitlines()
        figure = json.loads(lines[-1]) if out.returncode == 0 and lines else {}
        if "count" in figure and "error" not in figure:
            w["v8Count"] = figure["count"]
            counted += 1
        else:
            log(f"V8 does not count {w['id']}: {(out.stderr.strip() or figure.get('error') or 'no figure')[:200]}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(all_workloads, f, ensure_ascii=False, indent=1)
    log(f"V8's count of {counted} of {len(all_workloads)} workloads -> {path}")


def run(args):
    os.makedirs(args.out, exist_ok=True)
    workloads_file, text_dir = os.path.abspath(args.workloads), os.path.abspath(args.texts)
    with open(workloads_file, encoding="utf-8") as f:
        v8_counted = any("v8Count" in w for w in json.load(f))
    data_dir = os.path.abspath(args.data) if args.data else None
    runs = {"machine": describe_machine(), "started": now(), "sources": {}}
    pin = test_data(args.sources)
    if data_dir and pin:
        # With the number of answers the data asks in each encoding, which every engine's compliance is a share of.
        import answers
        # The version of Unicode V8 answered with, which an engine's compliance is judged at unless it names another.
        unicode = None
        try:
            with open(os.path.join(data_dir, "manifest.json"), encoding="utf-8") as f:
                unicode = unicode_version(json.load(f).get("unicode"))
        except (OSError, ValueError):
            pass
        runs["testData"] = dict(pin, unicode=unicode,
                                answers={k: v for k, v in answers.count(data_dir).items() if k != "files"})
    start = datetime.datetime.now(datetime.timezone.utc)

    def save():
        with open(os.path.join(args.out, "runs.json"), "w", encoding="utf-8") as f:
            json.dump(runs, f, indent=1)

    for source in load_sources(args.sources):
        save()
        sid, image = source["id"], source.get("image")
        record = {}
        runs["sources"][sid] = record
        limit = int(source.get("timeoutMinutes", 150)) * 60
        if args.budget_minutes:
            left = args.budget_minutes * 60 - (datetime.datetime.now(datetime.timezone.utc) - start).total_seconds()
            if left < 60:
                record["error"] = "the night's time ran out before it could start"
                log(f"{sid}: {record['error']}")
                continue
            limit = int(min(limit, left))
        if not image:
            record["error"] = "it names no image"
            continue
        if source.get("ref", "latest-release") != "latest-release":
            record["error"] = f"the ref policy '{source['ref']}' is not known"
            continue
        tag = pull(image, latest_release(source["repo"]))
        if not tag:
            record["error"] = f"its image {image} could not be pulled"
            continue
        record["image"], record["tag"] = image, tag
        digest = subprocess.run([ENGINE, "image", "inspect", "--format", "{{index .RepoDigests 0}}", f"{image}:{tag}"],
                                capture_output=True, text=True).stdout.strip()
        if digest:
            record["digest"] = digest.split("@", 1)[-1]
        out = os.path.abspath(os.path.join(args.out, sid))
        os.makedirs(out, exist_ok=True)
        os.chmod(out, 0o777)  # the image may run as a user other than the runner's
        data = os.path.join(out, "industry.json")
        record["started"] = now()
        log(f"{sid}: running {image}:{tag}")
        print(f"::group::{sid} {image}:{tag}", flush=True)
        try:
            mounts = ["-v", f"{workloads_file}:/workloads.json:ro", "-v", f"{text_dir}:/texts:ro"]
            if data_dir:
                mounts += ["-v", f"{data_dir}:/data:ro"]
            # V8 once a night, in the source that sources.json marks: the page shows it from that source alone.
            env = [] if source.get("v8") or not v8_counted else ["-e", "V8=0"]
            code = docker("run", "--rm", *env, *mounts, "-v", f"{out}:/out", f"{image}:{tag}", timeout=limit)
        except subprocess.TimeoutExpired:
            code = "timed out"
        print("::endgroup::", flush=True)
        record["finished"] = now()
        problem = None
        if code != 0:
            problem = f"its image failed ({code})"
        elif not os.path.isfile(data):
            problem = "its image wrote no /out/industry.json"
        else:
            try:
                with open(data, encoding="utf-8") as f:
                    problem = check(json.load(f))
            except ValueError as e:
                problem = f"its data file is not JSON ({e})"
            if problem:
                problem = f"its data file does not have the expected shape ({problem})"
        if problem:
            log(f"{sid}: {problem}")
            record["error"] = problem
        else:
            log(f"{sid}: done")
            record["file"] = data
    if runs.get("testData"):
        answers_at(runs, pin, os.path.abspath(args.work), data_dir)
    runs["finished"] = now()
    save()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["workloads", "texts", "counts", "data", "run"])
    parser.add_argument("--sources", default=os.path.join(ROOT, "sources.json"))
    parser.add_argument("--work", default="work")
    parser.add_argument("--workloads", default="workloads.json")
    parser.add_argument("--texts", default=os.path.expanduser("~/.local/share/corvus-regex-benchmarks"))
    parser.add_argument("--out", default="out-data")
    parser.add_argument("--data", help="data: where to fetch the test data; run: its data/ directory, given to every image at /data")
    parser.add_argument("--budget-minutes", type=int, default=0, help="run: no source runs past this many minutes from the start")
    args = parser.parse_args()
    if args.command == "workloads":
        args.out = args.workloads
    {"workloads": workloads, "texts": texts, "counts": counts, "data": data, "run": run}[args.command](args)


if __name__ == "__main__":
    main()

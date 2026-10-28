"""Runs every engine of the manifest on this machine, each from its repository's published container image.

    python3 tools/sources.py workloads [--sources sources.json] --work work --workloads workloads.json
        Clones the .NET source at its newest release whose image can be pulled into work/dotnet and writes the
        Industry workloads with its tools/benchmarks/v8/workloads.py: the list comes from one place. The tag is kept in
        work/pins.json, and the run command pulls the .NET image at it.

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
        with V8=0 checks its engines' counts against these instead of timing V8 itself. The counts are all or none: if
        V8 cannot count a workload (an error, or no figure within 600 s), the workloads that failed are logged, no
        workload carries a count, and every image times V8 itself.

    python3 tools/sources.py run --workloads workloads.json --texts DIR [--data DIR/data] [--budget-minutes N] --out out-data
        For each source: pulls `<image>:<tag>`, the tag of the repository's newest GitHub release whose image can be
        pulled, a package release or a harness release (`latest` only for a repository with no release at all; the
        .NET source at the release the workloads command took its workloads from, work/pins.json), and runs it as the
        contract says,

            docker run --rm --name <name> [-e V8=0] -v <workloads.json>:/workloads.json:ro -v <texts dir>:/texts:ro [-v <data>:/data:ro] -v <out>/<id>:/out <image>

        which writes /out/industry.json. When the workloads carry V8's counts (the counts command), every source but
        the one sources.json marks "v8": true runs with V8=0, so that V8 is timed (and run over the data) once a
        night rather than in every image: the page shows it once. When that source has had its turn and given no V8
        (its image failed, or could not be pulled), the next source runs without V8=0, and so on until one gives V8. Writes out-data/runs.json, after each source, so that a run cut short still
        has the sources it ran: per source, the data file (when it has the results-page shape), the image and tag
        that ran, the image's digest, the time it ran, and this machine's description. An image that cannot be
        pulled, fails or writes no usable file is recorded as such; tools/merge.py then shows the source as not run
        tonight. So is an image with no build for this machine's architecture (runs.json's architecture, x86_64 or
        arm64): the nightly runs every source on each, and an image built for x86-64 alone is not run on arm64. Each source's limit (timeoutMinutes) covers its pull and its run; a container still running at its
        limit is killed and removed before the next source starts. With --budget-minutes, no source runs past that
        many minutes from the start: each is given the less of its own limit and the time left, and one that would
        start with less than 10 minutes left is recorded as not run, with the minutes there were. Each image is removed
        once its source has run, and the free disk space is logged before each pull. Counts a
        source made at another commit of the data (an engine's compliance with a dataCommit), or for another version
        of Unicode (one with a unicode), are judged against what was asked of them: the answers of each such commit
        and version are counted into runs.json's testData.answersAt, those of every overlay the data has before the
        first source runs and those of another commit as soon as the source that names it has run.

Python 3 standard library only. GITHUB_TOKEN, when set, authenticates the GitHub API calls.
"""

import argparse
import datetime
import json
import os
import platform
import re
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from merge import check, is_v8, normalise_compliance, unicode_version  # noqa: E402

# The container engine: docker on the runner; CONTAINER_ENGINE=podman for a local run on a machine without docker.
ENGINE = os.environ.get("CONTAINER_ENGINE", "docker")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
# The least time a source is started with: no image finishes in less, and one stopped part-way is only a failure.
MIN_SECONDS = 10 * 60
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


def releases(repo):
    """The tags of the repository's published releases of either kind, newest first: package releases, and harness
    releases (a tag starting harness-), which publish the harness image alone when only the harness changed. GitHub's
    "latest" is not used: a harness release is marked not latest, so that the repository's Latest stays its package's.
    Raises when the API cannot be read after three tries."""
    for attempt in range(3):
        try:
            found = [r for r in api(f"repos/{repo}/releases?per_page=30") if not r.get("draft") and not r.get("prerelease")]
            return [r["tag_name"] for r in sorted(found, key=lambda r: r.get("published_at") or "", reverse=True)]
        except Exception as e:  # noqa: BLE001 (tried again, then raised)
            if attempt == 2:
                raise
            log(f"{repo}: its releases could not be read ({e}); trying again")
            time.sleep(10)


def pullable(image, tags, timeout=None):
    """The first of tags whose image pulls, newest first, or None. A release whose image is not published yet (its
    workflow still building) gives way to the release before it, never to `latest`, which is the image of unreleased
    work on the default branch; `latest` is pulled only for a repository with no release at all (tags empty)."""
    for tag in tags or ["latest"]:
        try:
            if docker("pull", "--quiet", f"{image}:{tag}", timeout=timeout) == 0:
                return tag
        except subprocess.TimeoutExpired:
            log(f"{image}:{tag}: the pull did not finish in its time")
            return None
        log(f"{image}:{tag} could not be pulled")
    return None


def pins_path(work):
    """Where the workloads command writes the tag it took the workloads from, which the run command pulls that source's
    image at, so that the image and the workloads come from one release."""
    return os.path.join(work, "pins.json")


def workloads(args):
    source = next((s for s in load_sources(args.sources) if s.get("language") == ".NET"), None)
    if source is None:
        raise SystemExit("sources: the manifest has no .NET source, whose workloads.py writes the workloads")
    tags = releases(source["repo"])
    # The newest release whose image is published, so that the image the run pulls is the release the workloads come
    # from; with none pullable, the newest release (the source is then shown as not run, the others still run).
    tag = (pullable(source["image"], tags) if source.get("image") else None) or (tags[0] if tags else "latest")
    path = os.path.abspath(os.path.join(args.work, source["id"]))
    command = ["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1"]
    branch = [] if tag == "latest" else ["--branch", tag]
    subprocess.run(command + branch + [f"https://github.com/{source['repo']}.git", path], check=True)
    log(f"workloads from {source['repo']} at {tag if branch else 'its default branch'}")
    with open(pins_path(args.work), "w", encoding="utf-8") as f:
        json.dump({source["id"]: tag}, f)
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


def architecture():
    """The machine's architecture as the page names it: x86_64 or arm64 (or what Python reports for another)."""
    machine = platform.machine().lower()
    return {"amd64": "x86_64", "x86_64": "x86_64", "aarch64": "arm64", "arm64": "arm64"}.get(machine, machine)


# The architecture of an image as Docker records it, for each architecture the page names.
IMAGE_ARCHITECTURE = {"x86_64": "amd64", "arm64": "arm64"}


def image_architecture(image, tag):
    """The architecture of a pulled image (amd64, arm64, ...), or "" when it cannot be read."""
    return subprocess.run([ENGINE, "image", "inspect", "--format", "{{.Architecture}}", f"{image}:{tag}"],
                          capture_output=True, text=True).stdout.strip()


def built_for(image, tag):
    """The Linux architectures an image's tag is built for (amd64, arm64, ...), read from its manifest without pulling
    it, or None when that cannot be read: a multi-platform index lists each, and a single image names its own."""
    try:
        out = subprocess.run([ENGINE, "manifest", "inspect", "--verbose", f"{image}:{tag}"], capture_output=True,
                             text=True, timeout=120)
        entries = json.loads(out.stdout) if out.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return None
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        return None
    found = set()
    for entry in entries:
        platform_ = ((entry or {}).get("Descriptor") or {}).get("platform") or {}
        if platform_.get("os") == "linux" and platform_.get("architecture"):
            found.add(platform_["architecture"])
    return found or None


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


def docker(*arguments, timeout=None, quiet=False):
    try:
        quieted = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL} if quiet else {}
        return subprocess.run([ENGINE, *arguments], timeout=timeout, **quieted).returncode
    except FileNotFoundError:
        log(f"{ENGINE} is not installed")
        return 127


def disk():
    """Logs the free space where images are kept: ten images are some 6 GB compressed, and a pull that finds the disk
    full fails as if the image were not there."""
    paths = [p for p in ("/var/lib/docker", "/") if os.path.exists(p)]
    out = subprocess.run(["df", "-h", *paths], capture_output=True, text=True).stdout.strip()
    for line in out.splitlines():
        log(f"disk: {line}")


def stop(name):
    """Stops and removes the container of that name. Killing the client of `docker run` (which is what a timeout does)
    leaves its container running under the daemon, where it would load the machine while the next sources are timed."""
    for command in (["kill", name], ["rm", "-f", name]):
        try:
            docker(*command, timeout=120, quiet=True)
        except subprocess.TimeoutExpired:
            log(f"{ENGINE} {' '.join(command)} did not finish")


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


def overlays(data_dir):
    """The versions of Unicode the data has an overlay for (manifest.json's unicode_overlays), as merge.py names them."""
    try:
        with open(os.path.join(data_dir, "manifest.json"), encoding="utf-8") as f:
            listed = json.load(f).get("unicode_overlays") or []
        return {unicode_version(o.get("unicode")) for o in listed if isinstance(o, dict)} - {None}
    except (OSError, ValueError, AttributeError):
        return set()


def answers_at(runs, pairs, pin, work, data_dir, tried):
    """Adds the answers asked in each encoding and grammar at each (commit, Unicode version) of pairs to
    runs["testData"]["answersAt"], keyed "<commit>|<version>", so that the page judges counts made at another commit
    or for another version against what was asked of them. A pair already counted, or already tried and not
    countable, is left as it is."""
    import answers
    unicode = runs["testData"].get("unicode")
    found = runs["testData"].setdefault("answersAt", {})
    for commit, version in sorted(pairs, key=str):
        key = f"{commit}|{version or ''}"
        if key in found or key in tried:
            continue
        tried.add(key)
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
    if not found:
        del runs["testData"]["answersAt"]


def counts(args):
    source = next((s for s in load_sources(args.sources) if s.get("language") == ".NET"), None)
    if source is None:
        raise SystemExit("sources: the manifest has no .NET source, whose industry.mjs counts the workloads")
    script = os.path.join(os.path.abspath(args.work), source["id"], "tools", "benchmarks", "v8", "industry.mjs")
    path = os.path.abspath(args.workloads)
    with open(path, encoding="utf-8") as f:
        all_workloads = json.load(f)
    env = dict(os.environ, CORVUS_REGEX_TEXTS=os.path.abspath(args.texts))
    uncounted = []
    for k, w in enumerate(all_workloads):
        w.pop("v8Count", None)
        # One turn of the interleaved run, as each image's harness starts it, timed as briefly as it allows: its count.
        try:
            out = subprocess.run(["node", script, "--one", path, str(k), "0.001", "1"], capture_output=True, text=True,
                                 env=env, timeout=600)
            lines = out.stdout.strip().splitlines()
            figure = json.loads(lines[-1]) if out.returncode == 0 and lines else {}
            why = out.stderr.strip() or (figure.get("error") if isinstance(figure, dict) else None) or "no figure"
        except subprocess.TimeoutExpired:
            figure, why = {}, "it did not finish in 600 s"
        except ValueError as e:
            figure, why = {}, f"its figure is not JSON ({e})"
        if isinstance(figure, dict) and "count" in figure and "error" not in figure:
            w["v8Count"] = figure["count"]
        else:
            uncounted.append(w["id"])
            log(f"V8 does not count {w['id']}: {why[:200]}")
    if uncounted:
        # A part of the counts is never handed out: an image given V8=0 would leave the uncounted workloads unchecked.
        # Without them every image times V8 itself, as before the counts, and the page shows V8 once.
        for w in all_workloads:
            w.pop("v8Count", None)
        log(f"V8 did not count {len(uncounted)} of {len(all_workloads)} workloads ({'; '.join(uncounted)}), so no "
            f"workload carries a count and every image times V8")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(all_workloads, f, ensure_ascii=False, indent=1)
    if not uncounted:
        log(f"V8's count of all {len(all_workloads)} workloads -> {path}")


def run(args):
    os.makedirs(args.out, exist_ok=True)
    workloads_file, text_dir = os.path.abspath(args.workloads), os.path.abspath(args.texts)
    with open(workloads_file, encoding="utf-8") as f:
        listed = json.load(f)
    # Every workload carries V8's count, or the images time V8 themselves (the counts command hands out all or none).
    v8_counted = bool(listed) and all("v8Count" in w for w in listed)
    data_dir = os.path.abspath(args.data) if args.data else None
    work = os.path.abspath(args.work)
    tried = set()
    # Unique to this run, for the containers' names.
    run_id = os.environ.get("GITHUB_RUN_ID") or datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
    try:
        with open(pins_path(work), encoding="utf-8") as f:
            pinned = json.load(f)
    except (OSError, ValueError):
        pinned = {}
    arch = architecture()
    runs = {"machine": describe_machine(), "architecture": arch, "started": now(), "sources": {}}
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
        # Before any source runs, the answers of every other version of Unicode the data has an overlay for, so that a
        # night cut short still judges an engine of another version by its version's answers; a commit a source names
        # is added when that source has run.
        answers_at(runs, {(pin["commit"], v) for v in overlays(data_dir) if v != unicode}, pin, work, data_dir, tried)
    start = datetime.datetime.now(datetime.timezone.utc)

    def save():
        with open(os.path.join(args.out, "runs.json"), "w", encoding="utf-8") as f:
            json.dump(runs, f, indent=1)

    listed_sources = load_sources(args.sources)
    # V8 once a night: the source sources.json marks times it, and when that source has had its turn without giving
    # V8 (its image failed, or could not be pulled), the next source does, and so on until one has.
    v8_source = next((s["id"] for s in listed_sources if s.get("v8")), None)
    v8_delivered = False
    for source in listed_sources:
        save()
        sid, image = source["id"], source.get("image")
        record = {}
        runs["sources"][sid] = record
        limit = int(source.get("timeoutMinutes", 150)) * 60
        if args.budget_minutes:
            left = args.budget_minutes * 60 - (datetime.datetime.now(datetime.timezone.utc) - start).total_seconds()
            if left < MIN_SECONDS:
                # Too little to finish in: a source started now would only be stopped, and say it failed.
                record["error"] = f"{max(0, int(left // 60))} minutes of the budget were left"
                log(f"{sid}: {record['error']}")
                continue
            limit = int(min(limit, left))
        # The source's limit covers its pull as well as its run.
        deadline = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=limit)

        def remaining():
            return (deadline - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        if not image:
            record["error"] = "it names no image"
            continue
        if source.get("ref", "latest-release") != "latest-release":
            record["error"] = f"the ref policy '{source['ref']}' is not known"
            continue
        if sid in pinned:
            tags = [pinned[sid]]  # the release the workloads were written from
        else:
            try:
                tags = releases(source["repo"])
            except Exception as e:  # noqa: BLE001
                record["error"] = f"its releases could not be read ({e})"
                log(f"{sid}: {record['error']}")
                continue
        # An image with no build for this machine is not pulled: on the arm64 runner that would be every image built
        # for x86-64 alone, gigabytes each, to no end.
        newest = (tags or ["latest"])[0]
        platforms = built_for(image, newest)
        if platforms and IMAGE_ARCHITECTURE.get(arch, arch) not in platforms:
            record["error"] = f"its image {image}:{newest} has no build for {arch} (it is built for {', '.join(sorted(platforms))})"
            log(f"{sid}: {record['error']}")
            continue
        disk()
        tag = pullable(image, tags, timeout=max(1, remaining()))
        if not tag:
            record["error"] = f"no release of its image {image} could be pulled ({', '.join(tags[:5]) or 'latest'})"
            log(f"{sid}: {record['error']}")
            continue
        # An image of one architecture pulls on a machine of another with only a warning, and then fails to start.
        built = image_architecture(image, tag)
        if built and built != IMAGE_ARCHITECTURE.get(arch, arch):
            record["error"] = f"its image {image}:{tag} has no build for {arch} (it is built for {built})"
            log(f"{sid}: {record['error']}")
            docker("image", "rm", f"{image}:{tag}", timeout=300, quiet=True)
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
        # A name of its own, so that a container whose time ran out can be found and stopped.
        name = re.sub(r"[^A-Za-z0-9_.-]", "-", f"bench-{sid}-{run_id}")
        try:
            mounts = ["-v", f"{workloads_file}:/workloads.json:ro", "-v", f"{text_dir}:/texts:ro"]
            if data_dir:
                mounts += ["-v", f"{data_dir}:/data:ro"]
            v8_turn = source.get("v8") or v8_source is None or (sid != v8_source and v8_source in runs["sources"])
            v8_on = not v8_counted or (not v8_delivered and v8_turn)
            env = [] if v8_on else ["-e", "V8=0"]
            if v8_on and v8_counted and sid != v8_source:
                log(f"{sid}: times V8 tonight, since {v8_source or 'no source'} has not")
            if remaining() <= 0:
                raise subprocess.TimeoutExpired("pull", limit)
            code = docker("run", "--rm", "--name", name, *env, *mounts, "-v", f"{out}:/out", f"{image}:{tag}",
                          timeout=remaining())
        except subprocess.TimeoutExpired:
            code = "timed out"
            stop(name)
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
            # Relative to runs.json, so that the merge finds it wherever the run's files are taken (the publish job
            # merges them on another runner).
            record["file"] = os.path.relpath(data, args.out)
            with open(data, encoding="utf-8") as f:
                if any(is_v8(i) for i in json.load(f)["impls"]):
                    v8_delivered = True
                    if v8_on:
                        record["v8"] = True  # this source timed the V8 the page shows
            if runs.get("testData"):
                answers_at(runs, asked(data, pin, runs["testData"].get("unicode")), pin, work, data_dir, tried)
        # Its image is not needed again tonight: the room it takes is the next source's.
        try:
            docker("image", "rm", f"{image}:{tag}", timeout=300, quiet=True)
        except subprocess.TimeoutExpired:
            log(f"{sid}: its image could not be removed")
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

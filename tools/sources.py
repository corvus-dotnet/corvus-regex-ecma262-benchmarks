"""Runs every engine of the manifest on this machine, each from its repository's published container image.

    python3 tools/sources.py workloads [--sources sources.json] --work work --workloads workloads.json
        Clones the .NET source at its latest release into work/dotnet and writes the Industry workloads with its
        tools/benchmarks/v8/workloads.py: the list comes from one place.

    python3 tools/sources.py texts --workloads workloads.json --texts DIR
        Downloads each text the workloads name (the Industry texts of dotnet/performance, gzipped, kept as they are)
        into DIR, unless it is there already.

    python3 tools/sources.py run --workloads workloads.json --texts DIR --out out-data
        For each source: pulls `<image>:<tag>`, the tag of the repository's latest GitHub release (or `latest` when
        there is no release or that tag cannot be pulled), and runs it as the contract says,

            docker run --rm -v <workloads.json>:/workloads.json:ro -v <texts dir>:/texts:ro -v <out>/<id>:/out <image>

        which writes /out/industry.json. Writes out-data/runs.json: per source, the data file (when it has the
        results-page shape), the image and tag that ran, the image's digest, the time it ran, and this machine's
        description. An image that cannot be pulled, fails or writes no usable file is recorded as such;
        tools/merge.py then shows the source as not run tonight.

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
from merge import check  # noqa: E402

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
    try:
        return api(f"repos/{repo}/releases/latest")["tag_name"]
    except Exception as e:  # no release yet, or the API refused: the image's latest tag is used
        log(f"{repo}: no latest release could be read ({e})")
        return None


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


def run(args):
    os.makedirs(args.out, exist_ok=True)
    workloads_file, text_dir = os.path.abspath(args.workloads), os.path.abspath(args.texts)
    runs = {"machine": describe_machine(), "started": now(), "sources": {}}
    for source in load_sources(args.sources):
        sid, image = source["id"], source.get("image")
        record = {}
        runs["sources"][sid] = record
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
            code = docker("run", "--rm", "-v", f"{workloads_file}:/workloads.json:ro", "-v", f"{text_dir}:/texts:ro",
                          "-v", f"{out}:/out", f"{image}:{tag}", timeout=int(source.get("timeoutMinutes", 150)) * 60)
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
    runs["finished"] = now()
    with open(os.path.join(args.out, "runs.json"), "w", encoding="utf-8") as f:
        json.dump(runs, f, indent=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["workloads", "texts", "run"])
    parser.add_argument("--sources", default=os.path.join(ROOT, "sources.json"))
    parser.add_argument("--work", default="work")
    parser.add_argument("--workloads", default="workloads.json")
    parser.add_argument("--texts", default=os.path.expanduser("~/.local/share/corvus-regex-benchmarks"))
    parser.add_argument("--out", default="out-data")
    args = parser.parse_args()
    if args.command == "workloads":
        args.out = args.workloads
    {"workloads": workloads, "texts": texts, "run": run}[args.command](args)


if __name__ == "__main__":
    main()

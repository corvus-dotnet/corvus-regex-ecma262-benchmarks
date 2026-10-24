"""The number of answers the ECMA-262 test data asks of an engine, in each encoding, by the data's own rule ("How a
runner judges an engine" in its README): what a compliance figure of 100% is a share of.

- Records and tests marked v8_deviation are left out.
- Each record is asked about under every grammar V8 found it valid in (unicode, legacy, and unicode_sets where the
  record has it). A grammar V8 found invalid asks for a verdict, which is counted only when it is wrong, so it adds
  no answer here.
- Each test is one answer over UTF-16 and, when its text holds no lone surrogate, one more over UTF-8.
- In captures.jsonl a test is seven answers over UTF-16 (exec, the global search, sticky, replace, replaceAll, split,
  split3) and five over UTF-8 when its text holds no lone surrogate (all but the splits). Sticky, which starts at
  position 1, is not asked of an empty text, nor over UTF-8 where position 1 falls between the halves of a
  supplementary character: UTF-8 has no such position, as it has no form of a lone surrogate.
- In ill-formed-utf8.jsonl a test holds bytes that are not UTF-8, and is one answer over UTF-8 alone (the right one
  a refusal) under each grammar the pattern is valid in.
- In exec/test262.jsonl (the exec calls of test262's tests, in a directory of its own) a record is a pattern with its
  own flags, in the one grammar they give (v, u, or neither: legacy), and a test is one call of exec: one answer over
  UTF-16 and, when its text holds no lone surrogate and its lastIndex does not fall between the halves of a pair, one
  more over UTF-8.

An engine's figure is its right answers over the answers of the encodings and the grammars it answers in, so an
answer its runner did not ask counts against it as a wrong one does. The counts are given in total, for each grammar
and for each file. The answers are V8's, from its version of Unicode; with --unicode, the counts are those of the data
with that version's overlay applied (data/unicode/<version>.jsonl: answers and validities that differ under it), as
an engine of that version is asked.

Python 3 standard library only.

Usage:
    python3 tools/answers.py <the test data's data directory> [--unicode <version>]
"""

import json
import math
import os
import sys


def lone(s):
    return any(0xD800 <= ord(c) <= 0xDFFF for c in s)


GRAMMARS = ("unicode", "legacy", "unicode_sets")
EXEC = "exec/test262.jsonl"


def units(s):
    """A str as UTF-16 code units (a pair's escapes read as one code point beyond U+FFFF become two)."""
    out = []
    for c in s:
        n = ord(c)
        out.extend([0xD800 + ((n - 0x10000) >> 10), 0xDC00 + ((n - 0x10000) & 0x3FF)] if n > 0xFFFF else [n])
    return out


def exec_answers(data_dir):
    """{grammar: [utf16, utf8]} for exec/test262.jsonl, or None when the data has no such file."""
    path = os.path.join(data_dir, EXEC)
    if not os.path.isfile(path):
        return None
    per = {g: [0, 0] for g in GRAMMARS}
    with open(path, encoding="utf-8", errors="surrogatepass") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            flags = record["flags"]
            a = per["unicode_sets" if "v" in flags else "unicode" if "u" in flags else "legacy"]
            for test in record["tests"]:
                if test.get("v8_deviation"):
                    continue
                text = units(test["text"])
                at = test["lastIndex"]
                at = len(text) + 1 if not math.isfinite(at) or at > len(text) else int(at)
                inside = 0 < at < len(text) and 0xDC00 <= text[at] <= 0xDFFF and 0xD800 <= text[at - 1] <= 0xDBFF
                a[0] += 1
                a[1] += 0 if lone(test["text"]) or inside else 1
    return per


def overlay(data_dir, unicode):
    """The overlay of a version of Unicode: {(file, line): [entries]}, or None when there is none."""
    path = os.path.join(data_dir, "unicode", f"{unicode}.jsonl")
    if not os.path.isfile(path):
        return None
    entries = {}
    with open(path, encoding="utf-8", errors="surrogatepass") as f:
        for line in f:
            if line.strip():
                e = json.loads(line)
                entries.setdefault((e["file"], e["line"]), []).append(e)
    return entries


def patched(record, entries):
    """A record with the overlay's entries for it applied, as unicode.js apply in the test data applies them."""
    for e in entries:
        if "valid" in e:
            record["valid"][e["grammar"]] = e["valid"]
            if not e["valid"]:
                for t in record.get("tests") or []:
                    t.pop(e["grammar"], None)
        else:
            record["tests"][e["test"]][e["grammar"]] = e["answer"]
    return record


def count(data_dir, unicode=None):
    """{"utf16": n, "utf8": n, "grammars": {grammar: {"utf16": n, "utf8": n}}, "files": {name: {...}}} for the data
    in data_dir, with the overlay of a version of Unicode applied when one is named. Raises LookupError when the data
    has no overlay for that version."""
    changes = overlay(data_dir, unicode) if unicode else {}
    if changes is None:
        raise LookupError(f"the test data has no overlay for Unicode {unicode}")
    files = {}
    by_grammar = {g: {"utf16": 0, "utf8": 0} for g in GRAMMARS}
    for name in sorted(f for f in os.listdir(data_dir) if f.endswith(".jsonl")):
        per = {g: [0, 0] for g in GRAMMARS}
        captures = name == "captures.jsonl"
        ill_formed = name == "ill-formed-utf8.jsonl"
        with open(os.path.join(data_dir, name), encoding="utf-8", errors="surrogatepass") as f:
            for number, line in enumerate(f, 1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if (name, number) in changes:
                    record = patched(record, changes[(name, number)])
                if record.get("v8_deviation"):
                    continue
                valid = record.get("valid", {})
                grammars = ["unicode", "legacy"] + (["unicode_sets"] if "unicode_sets" in valid else [])
                for grammar in grammars:
                    if not valid.get(grammar):
                        continue
                    a = per[grammar]
                    for test in record.get("tests") or []:
                        if ill_formed:
                            a[1] += 1
                            continue
                        if test.get("v8_deviation") or grammar not in test:
                            continue
                        text = test.get("text", "")
                        whole = not lone(text)
                        if captures:
                            a[0] += 7 if text else 6
                            if whole:
                                # Python reads a pair's escapes as one code point beyond U+FFFF.
                                mid = ord(text[0]) > 0xFFFF if text else False
                                a[1] += 5 if text and not mid else 4
                        else:
                            a[0] += 1
                            a[1] += 1 if whole else 0
        files[name] = {"utf16": sum(v[0] for v in per.values()), "utf8": sum(v[1] for v in per.values()),
                       "grammars": {g: {"utf16": v[0], "utf8": v[1]} for g, v in per.items()}}
        for g, v in per.items():
            by_grammar[g]["utf16"] += v[0]
            by_grammar[g]["utf8"] += v[1]
    # No exec call depends on the version of Unicode, so no overlay changes an answer of exec/test262.jsonl.
    per = exec_answers(data_dir)
    if per is not None:
        files[EXEC] = {"utf16": sum(v[0] for v in per.values()), "utf8": sum(v[1] for v in per.values()),
                       "grammars": {g: {"utf16": v[0], "utf8": v[1]} for g, v in per.items()}}
        for g, v in per.items():
            by_grammar[g]["utf16"] += v[0]
            by_grammar[g]["utf8"] += v[1]
    return {"utf16": sum(g["utf16"] for g in by_grammar.values()), "utf8": sum(g["utf8"] for g in by_grammar.values()),
            "grammars": by_grammar, "files": files}


def main():
    args = sys.argv[1:]
    unicode = None
    if "--unicode" in args:
        k = args.index("--unicode")
        unicode = args[k + 1]
        del args[k:k + 2]
    if len(args) != 1:
        raise SystemExit(__doc__.strip().splitlines()[-1].strip())
    print(json.dumps(count(args[0], unicode), indent=1))


if __name__ == "__main__":
    main()

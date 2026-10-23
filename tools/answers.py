"""The number of answers the ECMA-262 test data asks of an engine, in each encoding, by the data's own rule ("How a
runner judges an engine" in its README): what a compliance figure of 100% is a share of.

- Records and tests marked v8_deviation are left out.
- Each record is asked about under every grammar V8 found it valid in (unicode, legacy, and unicode_sets where the
  record has it). A grammar V8 found invalid asks for a verdict, which is counted only when it is wrong, so it adds
  no answer here.
- Each test is one answer over UTF-16 and, when its text holds no lone surrogate, one more over UTF-8.
- In captures.jsonl a test is seven answers over UTF-16 (exec, the global search, sticky, replace, replaceAll, split,
  split3) and five over UTF-8 when its text holds no lone surrogate (all but the splits); sticky is not asked of an
  empty text.

An engine's figure is its right answers over the answers of the encodings it answers in, so an answer its runner did
not ask counts against it as a wrong one does.

Python 3 standard library only.

Usage:
    python3 tools/answers.py <the test data's data directory>
"""

import json
import os
import sys


def lone(s):
    return any(0xD800 <= ord(c) <= 0xDFFF for c in s)


def count(data_dir):
    """{"utf16": n, "utf8": n, "files": {name: {"utf16": n, "utf8": n}}} for the data in data_dir."""
    files, total16, total8 = {}, 0, 0
    for name in sorted(f for f in os.listdir(data_dir) if f.endswith(".jsonl")):
        a16 = a8 = 0
        captures = name == "captures.jsonl"
        with open(os.path.join(data_dir, name), encoding="utf-8", errors="surrogatepass") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("v8_deviation"):
                    continue
                valid = record.get("valid", {})
                grammars = ["unicode", "legacy"] + (["unicode_sets"] if "unicode_sets" in valid else [])
                for grammar in grammars:
                    if not valid.get(grammar):
                        continue
                    for test in record.get("tests") or []:
                        if test.get("v8_deviation") or grammar not in test:
                            continue
                        text = test.get("text", "")
                        whole = not lone(text)
                        if captures:
                            a16 += 7 if text else 6
                            a8 += (5 if text else 4) if whole else 0
                        else:
                            a16 += 1
                            a8 += 1 if whole else 0
        files[name] = {"utf16": a16, "utf8": a8}
        total16 += a16
        total8 += a8
    return {"utf16": total16, "utf8": total8, "files": files}


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__.strip().splitlines()[-1].strip())
    print(json.dumps(count(sys.argv[1]), indent=1))


if __name__ == "__main__":
    main()

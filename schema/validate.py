#!/usr/bin/env python3
"""Checks data files against the results contract, schema/results.schema.json, with the Corvus JSON Schema evaluator.

    python3 -m pip install corvus-json-schema
    python3 schema/validate.py <data file> [<data file> ...]

The schema is first checked against the draft 2020-12 meta-schema, then each file against the schema, with `format`
asserted (a date must be a date). Every failure is printed with where it is in the file and in the schema. The exit
status is 0 when every file keeps to the schema, 1 when one does not, and 2 when the schema itself is not valid.

tools/merge.py checks three things a schema cannot say: that every engine id is unique, that results name only
engines in impls, and that an exclusion of an encoding names the one encoding the judge has no calls in.
"""
import json
import os
import sys

import corvus_json_schema as cjs

SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.schema.json")
USAGE = "python3 schema/validate.py <data file> [<data file> ...]"


def failures(validate, instance):
    """The failures of an instance, as lines: where in the instance, where in the schema, and why."""
    collector = cjs.JsonSchemaResultsCollector.create(cjs.ResultsLevel.DETAILED)
    if validate.evaluate(instance, collector):
        return []
    return [f"  {r.document_evaluation_location or '/'} ({r.schema_evaluation_location}): {r.message}"
            for r in collector.results if not r.is_match]


def main(paths):
    if not paths:
        raise SystemExit(USAGE)
    with open(SCHEMA, encoding="utf-8") as f:
        schema = json.load(f)
    meta = cjs.compile({"$ref": "https://json-schema.org/draft/2020-12/schema"}, assert_format=True)
    bad = failures(meta, schema)
    if bad:
        print(f"{SCHEMA} is not a valid draft 2020-12 schema:", *bad, sep="\n")
        return 2
    validate = cjs.compile(schema, assert_format=True)
    status = 0
    for path in paths:
        with open(path, encoding="utf-8") as f:
            bad = failures(validate, json.load(f))
        if bad:
            print(f"{path} does not keep to the results contract:", *bad, sep="\n")
            status = 1
        else:
            print(f"{path} keeps to the results contract")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

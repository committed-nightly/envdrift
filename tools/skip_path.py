"""Check that a run on a box without the parsers really skipped, and that
`ENVDRIFT_REQUIRE_ENGINES=1` turns exactly those skips into failures.

Why this exists
---------------

Every CI job in this repo installs the three parser libraries before running
pytest, so `conftest.absent()` -- the branch that decides between skipping and
failing -- has never once been executed in CI. A test that *fails* where it
should skip therefore ships green: `envdrift#2` did exactly that, and the only
thing that caught it was a human running the suite in a fresh venv by hand
(logbook#72).

The fix is a CI leg that installs nothing and runs the suite twice. That leg
needs an assertion, and "pytest exited 0" is not one -- a suite whose tests
stopped skipping and started passing vacuously also exits 0. So this compares
the two runs by *test id*:

    the tests that skipped without the switch
        ==
    the tests that failed with it

Both directions matter. The left side being empty means the skip path never
ran and the leg proved nothing. The right side differing means the switch and
the skip path have come apart -- which is the one thing neither run can notice
on its own, because each is individually green.

Reading pytest's JUnit XML rather than its summary line is deliberate. The
summary is a sentence written for a person, it is a different sentence under
`-q`, and `addopts = "-q"` plus a CI `-q` is `-qq`, which prints no counts at
all (logbook#52). The XML is the same shape either way.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _ids(path: Path, *tags: str) -> dict[str, str]:
    """Test ids in `path` whose case holds one of `tags`, mapped to its message.

    A `testcase` with no child element passed. One with a `<skipped>`,
    `<failure>` or `<error>` child did that instead.
    """
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise SystemExit(f"{path}: not readable as JUnit XML: {exc}")

    found = {}
    for case in root.iter("testcase"):
        for child in case:
            if child.tag in tags:
                name = f"{case.get('classname', '')}::{case.get('name', '')}"
                found[name] = (child.get("message") or "").strip()
                break
    return found


def _listing(ids: dict[str, str], limit: int = 8) -> str:
    lines = []
    for name in sorted(ids)[:limit]:
        message = ids[name]
        lines.append(f"    {name}\n        {message[:120]}" if message else f"    {name}")
    if len(ids) > limit:
        lines.append(f"    ... and {len(ids) - limit} more")
    return "\n".join(lines)


def check(default: Path, required: Path) -> list[str]:
    """Every way the two runs can disagree, as plain sentences. Empty is good."""
    skipped = _ids(default, "skipped")
    broke = _ids(default, "failure", "error")
    failed = _ids(required, "failure", "error")
    still_skipped = _ids(required, "skipped")

    problems = []

    # The envdrift#2 shape: a test that decided an engine was usable from
    # something other than what `parse()` asks, so it ran and failed rather
    # than skipping. Invisible on a box with the parsers installed.
    if broke:
        problems.append(
            f"{len(broke)} test(s) failed instead of skipping on a box with no "
            f"parsers installed:\n{_listing(broke)}"
        )

    if not skipped:
        problems.append(
            "nothing skipped in the default run, so the skip path never ran and "
            "this leg asserts nothing. Either the parsers are installed after "
            "all, or the tests have stopped skipping and are now passing over "
            "an engine they never asked."
        )

    # Only compare the two sets once both runs are coherent on their own;
    # otherwise every id shows up in the diff and buries the real sentence.
    if not broke and skipped:
        unmoved = {k: v for k, v in still_skipped.items() if k in skipped}
        if unmoved:
            problems.append(
                f"{len(unmoved)} test(s) skipped even with ENVDRIFT_REQUIRE_ENGINES "
                f"set, so the switch does not reach them:\n{_listing(unmoved)}"
            )
        extra = {k: v for k, v in failed.items() if k not in skipped}
        if extra:
            problems.append(
                f"{len(extra)} test(s) failed with ENVDRIFT_REQUIRE_ENGINES set but "
                f"did not skip without it, so the failure is not a missing "
                f"parser:\n{_listing(extra)}"
            )

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare a bare-box pytest run against the same run with "
            "ENVDRIFT_REQUIRE_ENGINES=1, and fail unless the skips and the "
            "failures are the same tests."
        )
    )
    parser.add_argument("default", type=Path, help="JUnit XML from `pytest`")
    parser.add_argument(
        "required", type=Path, help="JUnit XML from `ENVDRIFT_REQUIRE_ENGINES=1 pytest`"
    )
    args = parser.parse_args(argv)

    for path in (args.default, args.required):
        if not path.exists():
            raise SystemExit(f"{path}: no such file -- did pytest get --junit-xml?")

    problems = check(args.default, args.required)
    skipped = _ids(args.default, "skipped")

    if problems:
        print(f"skip path: {len(problems)} problem(s)\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}\n", file=sys.stderr)
        return 1

    print(
        f"skip path: {len(skipped)} test(s) skipped for want of a parser, and "
        f"the same {len(skipped)} failed with ENVDRIFT_REQUIRE_ENGINES set."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

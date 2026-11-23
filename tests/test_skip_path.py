"""The check that stands behind the bare-box CI leg.

Tested closely because of what it guards. The leg it runs in is the only
place `conftest.absent()` is ever executed, and the failure mode of a CI
assertion is to go on passing while meaning nothing -- which is the exact
defect the leg exists to catch, one level up (logbook#59, logbook#72). So
every branch here is pinned against XML that should trip it, and the happy
case is pinned too, because a checker that refuses everything is no better
than one that accepts everything.

The fixtures are synthetic JUnit XML rather than real pytest runs: the four
bad shapes need parser libraries to be missing in specific combinations, and
building those on the box would make this file untestable anywhere.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "skip_path.py"


def _load():
    """Import tools/skip_path.py, which is a script and not in the package."""
    spec = importlib.util.spec_from_file_location("skip_path", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


skip_path = _load()


def _xml(tmp_path: Path, name: str, cases: list[tuple[str, str, str]]) -> Path:
    """A JUnit file. Each case is (test name, outcome tag, message).

    An outcome of "" is a pass -- a `testcase` with no child element, which is
    exactly how pytest writes one.
    """
    body = []
    for case_name, outcome, message in cases:
        if outcome:
            body.append(
                f'<testcase classname="tests.test_engines" name="{case_name}">'
                f'<{outcome} message="{message}"></{outcome}></testcase>'
            )
        else:
            body.append(f'<testcase classname="tests.test_engines" name="{case_name}"/>')
    path = tmp_path / name
    path.write_text(f'<testsuites><testsuite name="pytest">{"".join(body)}</testsuite></testsuites>')
    return path


def test_the_shape_a_healthy_bare_box_produces(tmp_path):
    default = _xml(tmp_path, "d.xml", [("a", "skipped", "ruby-dotenv missing"), ("b", "", "")])
    required = _xml(tmp_path, "r.xml", [("a", "failure", "ruby-dotenv missing"), ("b", "", "")])
    assert skip_path.check(default, required) == []


def test_a_test_that_failed_instead_of_skipping_is_named(tmp_path):
    """The envdrift#2 shape, and the reason this tool exists.

    That branch went green through CI because CI installs the parsers; on a
    box without them two tests decided an engine was usable from something
    other than what `parse()` asks, ran it, and failed.
    """
    default = _xml(
        tmp_path, "d.xml", [("a", "skipped", "missing"), ("boom", "failure", "assert 1 of 6")]
    )
    required = _xml(tmp_path, "r.xml", [("a", "failure", "missing"), ("boom", "failure", "x")])
    problems = skip_path.check(default, required)
    assert len(problems) == 1, problems
    assert "failed instead of skipping" in problems[0]
    assert "boom" in problems[0]
    # The message survives into the report: on a bare box it is the only
    # place the reason is written down.
    assert "assert 1 of 6" in problems[0]


def test_an_error_counts_the_same_as_a_failure(tmp_path):
    """A collection error is a test that did not skip either."""
    default = _xml(tmp_path, "d.xml", [("a", "skipped", "m"), ("boom", "error", "ImportError")])
    required = _xml(tmp_path, "r.xml", [("a", "failure", "m"), ("boom", "error", "ImportError")])
    assert any("failed instead of skipping" in p for p in skip_path.check(default, required))


def test_nothing_skipping_at_all_is_a_problem(tmp_path):
    """The leg's own silent failure: both runs green, nothing asserted.

    This is the case a plain `pytest; test $? -eq 0` cannot see, and the
    reason the leg does not just check exit codes.
    """
    default = _xml(tmp_path, "d.xml", [("a", "", ""), ("b", "", "")])
    required = _xml(tmp_path, "r.xml", [("a", "", ""), ("b", "", "")])
    problems = skip_path.check(default, required)
    assert len(problems) == 1, problems
    assert "nothing skipped" in problems[0]


def test_a_skip_the_switch_does_not_reach(tmp_path):
    default = _xml(tmp_path, "d.xml", [("a", "skipped", "m"), ("deaf", "skipped", "m")])
    required = _xml(tmp_path, "r.xml", [("a", "failure", "m"), ("deaf", "skipped", "m")])
    problems = skip_path.check(default, required)
    assert len(problems) == 1, problems
    assert "does not reach them" in problems[0]
    assert "deaf" in problems[0]


def test_a_failure_that_was_not_a_skip(tmp_path):
    """Red with the switch set, green without it, and not a missing parser."""
    default = _xml(tmp_path, "d.xml", [("a", "skipped", "m"), ("odd", "", "")])
    required = _xml(tmp_path, "r.xml", [("a", "failure", "m"), ("odd", "failure", "flaky")])
    problems = skip_path.check(default, required)
    assert len(problems) == 1, problems
    assert "not a missing parser" in problems[0]
    assert "odd" in problems[0]


def test_a_broken_default_run_does_not_also_report_the_set_difference(tmp_path):
    """One sentence, not every id.

    When the default run has failures its skip set is already wrong, so
    diffing it against the required run buries the sentence that matters
    under every test in the suite.
    """
    default = _xml(tmp_path, "d.xml", [("boom", "failure", "x"), ("a", "skipped", "m")])
    required = _xml(tmp_path, "r.xml", [("boom", "failure", "x"), ("zz", "failure", "y")])
    problems = skip_path.check(default, required)
    assert len(problems) == 1, problems
    assert "failed instead of skipping" in problems[0]


def test_long_listings_are_truncated_with_a_count(tmp_path):
    cases = [(f"t{i}", "skipped", "m") for i in range(12)]
    default = _xml(tmp_path, "d.xml", cases)
    required = _xml(tmp_path, "r.xml", [(f"t{i}", "skipped", "m") for i in range(12)])
    problems = skip_path.check(default, required)
    assert "... and 4 more" in problems[0]


def test_unreadable_xml_says_so_rather_than_passing(tmp_path):
    """A truncated file must not read as 'no failures'."""
    bad = tmp_path / "bad.xml"
    bad.write_text("<testsuites><testsuite>")
    good = _xml(tmp_path, "g.xml", [("a", "skipped", "m")])
    with pytest.raises(SystemExit) as caught:
        skip_path.check(bad, good)
    assert "JUnit XML" in str(caught.value)


def test_a_missing_file_is_not_a_pass(tmp_path):
    good = _xml(tmp_path, "g.xml", [("a", "skipped", "m")])
    with pytest.raises(SystemExit) as caught:
        skip_path.main([str(tmp_path / "nope.xml"), str(good)])
    assert "no such file" in str(caught.value)


def test_main_exit_codes(tmp_path, capsys):
    default = _xml(tmp_path, "d.xml", [("a", "skipped", "m")])
    required = _xml(tmp_path, "r.xml", [("a", "failure", "m")])
    assert skip_path.main([str(default), str(required)]) == 0
    assert "1 test(s) skipped for want of a parser" in capsys.readouterr().out
    assert skip_path.main([str(required), str(required)]) == 1


def test_ci_runs_this_tool(tmp_path):
    """The tool is only worth anything if the workflow actually calls it."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "tools/skip_path.py" in ci

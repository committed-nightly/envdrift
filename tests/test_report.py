import json

from envdrift.compare import Result, build
from envdrift.hazards import Hazard
from envdrift.report import to_json, to_text


def r(name, values=None, **kw):
    return Result(name, values=values, **kw)


def test_only_disagreements_are_printed_by_default():
    cmp = build("f", [r("a", {"SAME": "1", "DIFF": "x"}), r("b", {"SAME": "1", "DIFF": "y"})])
    text = to_text(cmp)
    assert "DIFF" in text
    assert "SAME" not in text


def test_all_prints_the_agreed_keys_too():
    cmp = build("f", [r("a", {"SAME": "1"}), r("b", {"SAME": "1"})])
    assert "SAME" in to_text(cmp, show_all=True)


def test_values_are_shown_with_their_invisible_bytes():
    cmp = build("f", [r("a", {"K": "1\r"}), r("b", {"K": "1"})])
    text = to_text(cmp)
    assert "'1\\r'" in text


def test_redact_hides_the_value_but_still_separates_outcomes():
    cmp = build("f", [r("a", {"K": "hunter2"}), r("b", {"K": "hunter3"})])
    text = to_text(cmp, redact=True)
    assert "hunter" not in text
    assert "7 chars" in text
    # Two different secrets must not render identically, or the drift vanishes.
    digests = {line.split()[0] for line in text.splitlines() if line.strip().startswith("<")}
    assert len(digests) == 2


def test_redact_applies_to_json_too():
    cmp = build("f", [r("a", {"K": "hunter2"}), r("b", {"K": "hunter3"})])
    payload = json.loads(to_json(cmp, redact=True))
    values = payload["keys"][0]["outcomes"]
    assert all("value" not in o["outcome"] for o in values)
    assert all(o["outcome"]["length"] == 7 for o in values)


def test_held_back_and_unavailable_are_named_separately():
    cmp = build(
        "f",
        [
            r("a", {"K": "1"}),
            r("ruby-dotenv", held_back="would execute command substitution"),
            r("compose", unavailable="docker is not on PATH"),
        ],
    )
    text = to_text(cmp)
    assert "held back" in text and "ruby-dotenv" in text
    assert "not available" in text and "docker is not on PATH" in text


def test_executed_section_names_the_engines_that_run_the_line():
    cmp = build(
        "f",
        [r("node", {"K": "$(id)"}), r("bash", {"K": "uid=0"})],
        [Hazard("$(", 3, "K=$(id)")],
    )
    text = to_text(cmp)
    assert "executed, not read" in text
    assert "line 3" in text
    assert "bash" in text.split("executed, not read")[1]
    # node does not execute anything, so it must not be listed there.
    assert "node" not in text.split("executed, not read")[1].split("\n\n")[0]


def test_no_executed_section_when_no_engine_runs_the_construct():
    cmp = build("f", [r("node", {"K": "$(id)"})], [Hazard("$(", 1, "K=$(id)")])
    assert "executed, not read" not in to_text(cmp)


def test_summary_counts_the_disagreeing_keys():
    cmp = build("f", [r("a", {"X": "1", "Y": "1"}), r("b", {"X": "2", "Y": "1"})])
    assert "1 of 2 keys differ between parsers" in to_text(cmp)


def test_summary_says_so_when_everyone_agreed():
    cmp = build("f", [r("a", {"X": "1"}), r("b", {"X": "1"})])
    assert "2 parsers agreed on every one of 1 key" in to_text(cmp)


def test_summary_is_honest_when_only_one_parser_ran():
    cmp = build("f", [r("a", {"X": "1"}), r("b", unavailable="nope")])
    assert "nothing to compare" in to_text(cmp)


def test_a_split_on_validity_is_reported_even_with_no_key_differences():
    cmp = build("f", [r("a", {"X": "1"}), r("b", error="unexpected EOF")])
    text = to_text(cmp)
    assert "rejected the file" in text
    assert "1 parser rejected the file that 1 parser read" in text


def test_long_values_are_truncated():
    cmp = build("f", [r("a", {"K": "x" * 500}), r("b", {"K": "y"})])
    line = [ln for ln in to_text(cmp).splitlines() if "xxx" in ln][0]
    assert len(line) < 200
    assert "..." in line


def test_json_shape_is_stable():
    cmp = build("f", [r("a", {"K": "1"}), r("b", {})], [Hazard("$(", 1, "K=1")])
    payload = json.loads(to_json(cmp))
    assert payload["path"] == "f"
    assert payload["drifted"] is True
    assert payload["keys"][0]["key"] == "K"
    assert payload["keys"][0]["outcomes"][1]["outcome"] == {"kind": "absent"}
    assert payload["engines"]["ran"] == [
        {"engine": "a", "version": None, "note": None},
        {"engine": "b", "version": None, "note": None},
    ]
    assert payload["hazards"][0]["line"] == 1

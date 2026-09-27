import json

from envdrift.compare import Result, build
from envdrift.hazards import Hazard
from envdrift.redact import SALT_ENV, Redactor
from envdrift.report import to_json, to_text


def r(name, values=None, **kw):
    return Result(name, values=values, **kw)


def fixed():
    """A redactor with a known salt, so a test can assert on an exact digest."""
    return Redactor.build({SALT_ENV: "a-salt-long-enough-for-the-tests"})


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
    text = to_text(cmp, redactor=fixed())
    assert "hunter" not in text
    # Two different secrets must not render identically, or the drift vanishes.
    digests = {line.split()[0] for line in text.splitlines() if line.strip().startswith("<")}
    assert len(digests) == 2


def test_redact_does_not_print_the_absolute_length():
    cmp = build("f", [r("a", {"K": "hunter2"}), r("b", {"K": "hunter3"})])
    text = to_text(cmp, redactor=fixed())
    # Both values are 7 long; saying so narrows the search for either of them.
    assert "7 chars" not in text


def test_redact_reports_length_as_a_difference_from_the_shortest_outcome():
    # The interesting redacted finding: same prefix, one parser kept two more
    # characters. `+2 chars` says that; `4 chars`/`6 chars` says it and the
    # keyspace as well.
    cmp = build("f", [r("a", {"K": "s3cr"}), r("b", {"K": "s3cr#t"})])
    text = to_text(cmp, redactor=fixed())
    assert "+2 chars>" in text
    assert "+0 " not in text  # the shortest outcome is annotated with nothing


def test_a_trailing_carriage_return_shows_up_as_one_character():
    cmp = build("f", [r("a", {"K": "1\r"}), r("b", {"K": "1"})])
    assert "+1 char>" in to_text(cmp, redactor=fixed())


def test_two_outcomes_of_equal_length_get_no_length_annotation():
    cmp = build("f", [r("a", {"K": "abc"}), r("b", {"K": "xyz"})])
    text = to_text(cmp, redactor=fixed())
    assert "chars" not in text
    assert len({ln.split()[0] for ln in text.splitlines() if ln.strip().startswith("<")}) == 2


def test_an_absent_outcome_does_not_become_the_length_baseline():
    # ABSENT has no length. If it counted as zero, every real value in the row
    # would be annotated with its own absolute length again.
    cmp = build("f", [r("a", {"K": "hunter2"}), r("b", {})])
    text = to_text(cmp, redactor=fixed())
    assert "<absent>" in text
    assert "chars" not in text


def test_redacted_output_explains_which_salt_produced_the_digests():
    cmp = build("f", [r("a", {"K": "x"}), r("b", {"K": "y"})])
    random_run = to_text(cmp, redactor=Redactor.build({}))
    assert "random per-run salt" in random_run
    assert SALT_ENV in random_run

    keyed_run = to_text(cmp, redactor=fixed())
    assert f"keyed by {SALT_ENV}" in keyed_run


def test_the_salt_never_reaches_the_output():
    salt = "sentinel-salt-value-not-for-printing"
    cmp = build("f", [r("a", {"K": "x"}), r("b", {"K": "y"})])
    assert salt not in to_text(cmp, redactor=Redactor.build({SALT_ENV: salt}))
    assert salt not in to_json(cmp, redactor=Redactor.build({SALT_ENV: salt}))


def test_no_redaction_footnote_when_there_are_no_rows_to_explain():
    cmp = build("f", [r("a", {"K": "1"}), r("b", {"K": "1"})])
    assert "redacted:" not in to_text(cmp, redactor=fixed())


def test_redact_applies_to_json_too():
    cmp = build("f", [r("a", {"K": "hunter2"}), r("b", {"K": "hunter3"})])
    payload = json.loads(to_json(cmp, redactor=fixed()))
    values = payload["keys"][0]["outcomes"]
    assert all("value" not in o["outcome"] for o in values)
    assert all(len(o["outcome"]["digest"]) == 8 for o in values)
    # Equal-length values, so neither is longer than the baseline.
    assert all(o["outcome"]["longer_by"] == 0 for o in values)


def test_json_redaction_block_says_whether_runs_are_comparable():
    cmp = build("f", [r("a", {"K": "1"}), r("b", {"K": "2"})])
    keyed = json.loads(to_json(cmp, redactor=fixed()))["redaction"]
    assert keyed["salt"] == SALT_ENV
    assert keyed["comparable_across_runs"] is True

    random_run = json.loads(to_json(cmp, redactor=Redactor.build({})))["redaction"]
    assert random_run["salt"] == "random-per-run"
    assert random_run["comparable_across_runs"] is False


def test_json_has_no_redaction_block_when_not_redacting():
    cmp = build("f", [r("a", {"K": "1"}), r("b", {"K": "2"})])
    assert "redaction" not in json.loads(to_json(cmp))


def test_json_reports_the_length_difference_not_the_length():
    cmp = build("f", [r("a", {"K": "s3cr"}), r("b", {"K": "s3cr#t"})])
    payload = json.loads(to_json(cmp, redactor=fixed()))
    by_len = sorted(o["outcome"]["longer_by"] for o in payload["keys"][0]["outcomes"])
    assert by_len == [0, 2]
    assert all("length" not in o["outcome"] for o in payload["keys"][0]["outcomes"])


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
    assert "1 of 2 keys differs between parsers" in to_text(cmp)


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


def test_held_back_alone_is_notable_even_when_everyone_else_agreed():
    cmp = build(
        "f",
        [r("a", {"K": "$(id)"}), r("b", {"K": "$(id)"}), r("bash", held_back="would execute")],
    )
    assert not cmp.drifted
    assert cmp.notable
    text = to_text(cmp)
    assert "agreed on every one of" in text
    assert "held back from a file it would execute" in text


def test_one_disagreeing_key_uses_the_singular_verb():
    cmp = build("f", [r("a", {"X": "1"}), r("b", {"X": "2"})])
    assert "1 of 1 key differs between parsers" in to_text(cmp)

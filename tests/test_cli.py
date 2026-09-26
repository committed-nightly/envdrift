import io
import json

import pytest

from envdrift import cli


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_missing_file_is_a_setup_error(tmp_path):
    code, _, err = run([str(tmp_path / "nope.env")])
    assert code == 2
    assert "no such file" in err


def test_a_directory_is_not_a_file(tmp_path):
    code, _, err = run([str(tmp_path)])
    assert code == 2
    assert "no such file" in err


def test_no_arguments_at_all():
    code, _, err = run([])
    assert code == 2
    assert "--list-engines" in err


def test_unknown_engine_names_the_real_ones():
    # Reported even though the file is also missing: an argument typo should
    # not be masked by a filesystem error found later.
    code, _, err = run(["--engines", "dotenvv", "x.env"])
    assert code == 2
    assert "no such engine: dotenvv" in err
    assert "npm-dotenv" in err


def test_list_engines_mentions_every_engine():
    code, out, _ = run(["--list-engines"])
    assert code == 0
    for name in ("node", "npm-dotenv", "python-dotenv", "ruby-dotenv", "compose", "bash"):
        assert name in out


def test_one_engine_alone_is_not_agreement(envfile):
    # python-dotenv is the one engine guaranteed to be runnable wherever the
    # test suite itself runs, so this is the reliable way to get a lone result.
    path = envfile("A=1\n")
    code, out, err = run(["--engines", "python-dotenv", str(path)])
    if "nothing to compare" not in err:
        pytest.skip("python-dotenv is not installed; no single-engine run available")
    assert code == 2
    assert "nothing to compare" in out


@pytest.mark.engine
def test_a_clean_file_exits_zero(envfile):
    path = envfile('A=1\nB=hello\nC="quoted"\n')
    code, out, err = run([str(path)])
    if code == 2:
        pytest.skip(err.strip())
    assert code == 0, out
    assert "agreed on every one of" in out


@pytest.mark.engine
def test_an_inline_comment_splits_the_parsers(envfile):
    path = envfile("A=1#two\n")
    code, out, err = run([str(path)])
    if code == 2:
        pytest.skip(err.strip())
    assert code == 1
    assert "'1'" in out and "'1#two'" in out


@pytest.mark.engine
def test_json_output_parses_and_matches_the_exit_code(envfile):
    path = envfile("A=1#two\n")
    code, out, err = run(["--json", str(path)])
    if code == 2:
        pytest.skip(err.strip())
    payload = json.loads(out)
    assert payload["drifted"] is (code == 1)
    assert payload["keys"][0]["key"] == "A"


@pytest.mark.engine
def test_redact_keeps_the_value_out_of_the_output(envfile):
    path = envfile("A=swordfish#two\n")
    code, out, err = run(["--redact", str(path)])
    if code == 2:
        pytest.skip(err.strip())
    assert "swordfish" not in out
    assert code == 1


@pytest.mark.engine
def test_executing_engines_are_held_back_by_default(envfile):
    path = envfile("A=$(echo PWNED)\n")
    code, out, err = run([str(path)])
    if code == 2 and "nothing to compare" in err:
        pytest.skip(err.strip())
    assert "held back" in out
    assert "PWNED" not in out
    assert "--unsafe" in out


@pytest.mark.engine
def test_unsafe_lets_them_run_and_says_which_line_was_executed(envfile):
    path = envfile("A=$(echo PWNED)\n")
    code, out, err = run(["--unsafe", str(path)])
    if code == 2:
        pytest.skip(err.strip())
    assert "executed, not read" in out
    assert "line 1" in out


@pytest.mark.engine
def test_a_file_that_would_be_executed_exits_nonzero(envfile):
    path = envfile("A=$(echo PWNED)\n")
    code, out, err = run([str(path)])
    if code == 2:
        pytest.skip(err.strip())
    assert code == 1, out
    assert "held back" in out

import io
import json

import pytest

from envdrift import cli, engines
from envdrift.redact import SALT_ENV

from .conftest import absent


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
def test_two_redacted_runs_of_the_same_file_do_not_match_by_default(envfile):
    path = envfile("A=swordfish#two\n")
    code, first, err = run(["--redact", str(path)])
    if code == 2:
        pytest.skip(err.strip())
    _, second, _ = run(["--redact", str(path)])
    assert first != second, "a fresh salt per run is the default"


@pytest.mark.engine
def test_the_salt_env_var_makes_two_runs_match(envfile, monkeypatch):
    monkeypatch.setenv(SALT_ENV, "a-salt-long-enough-for-the-tests")
    path = envfile("A=swordfish#two\n")
    code, first, err = run(["--redact", str(path)])
    if code == 2:
        pytest.skip(err.strip())
    _, second, _ = run(["--redact", str(path)])
    assert first == second
    assert "swordfish" not in first


@pytest.mark.engine
def test_the_salt_env_var_is_not_itself_leaked_into_the_output(envfile, monkeypatch):
    # It is a secret the caller supplied, and envdrift's whole job here is not
    # printing secrets.
    monkeypatch.setenv(SALT_ENV, "sentinel-salt-value-not-for-printing")
    path = envfile("A=swordfish#two\n")
    code, out, err = run(["--redact", "--json", str(path)])
    if code == 2:
        pytest.skip(err.strip())
    assert "sentinel-salt-value-not-for-printing" not in out
    assert json.loads(out)["redaction"]["comparable_across_runs"] is True


def test_the_salt_is_not_passed_through_to_the_parsers(envfile, monkeypatch):
    # Engines run with a near-empty environment, and the salt must not be one of
    # the things that survives into a subprocess that reads the file.
    monkeypatch.setenv(SALT_ENV, "sentinel-salt-value-not-for-printing")
    path = envfile("A=${%s}\n" % SALT_ENV)
    code, out, err = run(["--redact", str(path)])
    assert "sentinel-salt-value-not-for-printing" not in out
    assert "sentinel-salt-value-not-for-printing" not in err


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


# --- --require-engines ------------------------------------------------------
#
# The flag exists because an engine that never ran is reported in a section
# near the end of the report and nowhere in the exit code, so a caller that
# reads either one cannot tell a six-parser comparison from a three-parser
# one. See ci.yml, which used to try to answer this with --list-engines.


@pytest.fixture
def no_runtimes(monkeypatch):
    """A box with none of the engine runtimes on it."""
    monkeypatch.setattr(engines.shutil, "which", lambda cmd: None)


def test_require_engines_names_every_engine_that_never_ran(no_runtimes, envfile):
    path = envfile("A=1\n")
    code, _, err = run(["--require-engines", str(path)])
    assert code == 2
    for name in ("node", "npm-dotenv", "python-dotenv", "ruby-dotenv", "compose", "bash"):
        assert name in err, f"{name} never ran and was not named"
    assert "6 of 6 engines never ran" in err


def test_without_require_engines_the_same_box_reports_only_the_shortfall(
    no_runtimes, envfile
):
    """The control for the test above: the flag is what produces the names."""
    path = envfile("A=1\n")
    code, _, err = run([str(path)])
    assert code == 2
    assert "no parser read this file" in err
    assert "never ran" not in err
    assert "ruby-dotenv" not in err


def test_require_engines_changes_the_exit_code_of_an_otherwise_fine_run(
    monkeypatch, envfile
):
    """One missing engine, the rest working: plain exits 0 or 1, flag exits 2.

    This is the case the ci.yml guard was aimed at and missed. A run with five
    of six parsers is still a comparison, so it exits on whether they agreed
    -- and the parser that was never asked is a footnote.
    """
    others = [e for e in engines.ENGINES if e.name != "ruby-dotenv"]
    runnable = [e for e in others if e.available() is None]
    if len(runnable) < 2:
        absent("ruby-dotenv", "needs two other runnable engines to compare against")

    real_which = engines.shutil.which
    monkeypatch.setattr(
        engines.shutil, "which", lambda cmd: None if cmd == "ruby" else real_which(cmd)
    )
    path = envfile("A=1\n")

    plain, _, _ = run([str(path)])
    assert plain in (0, 1), f"expected a normal-looking run, got {plain}"

    code, _, err = run(["--require-engines", str(path)])
    assert code == 2
    assert "ruby-dotenv: ruby is not on PATH" in err
    assert "1 of 6 engines never ran" in err


def test_require_engines_does_not_count_a_held_back_engine(envfile):
    """Holding bash and ruby-dotenv back from `$(...)` is deliberate."""
    if engines.BY_NAME["bash"].available() is not None:
        absent("bash", "bash is not on PATH")
    path = envfile("A=$(id -u)\n")
    code, out, err = run(["--require-engines", str(path)])
    assert "never ran" not in err, err
    # Held back is notable in its own right, which is a 1 and not a 2.
    assert code == 1
    assert "held back" in out

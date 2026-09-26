"""What each parser actually does, measured rather than assumed.

Every expectation here was read off the real parser on a real box, and the
README quotes these same cases. If one of these starts failing it means a
parser changed its mind, which is exactly the thing envdrift exists to notice
-- so the test failing is the correct outcome, not a flake to paper over.

Each case skips rather than fails when its engine is not installed.
"""

import pytest

from envdrift.engines import BY_NAME

from .conftest import parse

ABSENT = object()
REJECTED = object()

#: case name -> (file body, {engine: expected value for key "A"})
CASES = {
    # A `#` with no space before it. Three parsers call it a comment, three
    # keep it, and the value is a URL fragment or a password often enough for
    # this to matter.
    "inline-comment, no space": (
        "A=1#two\n",
        {
            "node": "1",
            "npm-dotenv": "1",
            "ruby-dotenv": "1",
            "python-dotenv": "1#two",
            "compose": "1#two",
            "bash": "1#two",
        },
    ),
    # With a space, everybody agrees it is a comment.
    "inline-comment, with space": (
        "A=1 #two\n",
        {
            "node": "1",
            "npm-dotenv": "1",
            "ruby-dotenv": "1",
            "python-dotenv": "1",
            "compose": "1",
            "bash": "1",
        },
    ),
    # Interpolation, bare name. Node's parsers do not interpolate at all.
    'double-quoted "$B"': (
        'B=zzz\nA="$B"\n',
        {
            "node": "$B",
            "npm-dotenv": "$B",
            "python-dotenv": "$B",
            "ruby-dotenv": "zzz",
            "compose": "zzz",
            "bash": "zzz",
        },
    ),
    # Braced. python-dotenv moves camp: it does `${B}` and not `$B`.
    'double-quoted "${B}"': (
        'B=zzz\nA="${B}"\n',
        {
            "node": "${B}",
            "npm-dotenv": "${B}",
            "python-dotenv": "zzz",
            "ruby-dotenv": "zzz",
            "compose": "zzz",
            "bash": "zzz",
        },
    ),
    # Three different answers, including Node quietly eating the backticks.
    "backticks": (
        "A=`echo P`\n",
        {
            "node": "echo P",
            "npm-dotenv": "echo P",
            "python-dotenv": "`echo P`",
            "ruby-dotenv": "`echo P`",
            "compose": "`echo P`",
            "bash": "P",
        },
    ),
    # Every dotenv parser turns \n into a newline inside double quotes. The one
    # that is actually a shell does not.
    'escape "a\\nb"': (
        'A="a\\nb"\n',
        {
            "node": "a\nb",
            "npm-dotenv": "a\nb",
            "python-dotenv": "a\nb",
            "ruby-dotenv": "a\nb",
            "compose": "a\nb",
            "bash": "a\\nb",
        },
    ),
    # A file edited on Windows. The carriage return survives only under source.
    "CRLF line endings": (
        "A=1\r\n",
        {
            "node": "1",
            "npm-dotenv": "1",
            "python-dotenv": "1",
            "ruby-dotenv": "1",
            "compose": "1",
            "bash": "1\r",
        },
    ),
    # `A=a b` is not an assignment in shell: it runs `b` with A set for that one
    # command, so nothing is left behind. The dotenv parsers all read a value.
    "unquoted value with a space": (
        "A=a b\n",
        {
            "node": "a b",
            "npm-dotenv": "a b",
            "python-dotenv": "a b",
            "ruby-dotenv": "a b",
            "compose": "a b",
            "bash": ABSENT,
        },
    ),
    "spaces around the equals": (
        "A = 1\n",
        {
            "node": "1",
            "npm-dotenv": "1",
            "python-dotenv": "1",
            "ruby-dotenv": "1",
            "compose": "1",
            "bash": ABSENT,
        },
    ),
    # An unterminated quote is where they stop even agreeing on whether the file
    # is a file: two read a value, one drops the key, one rejects it outright.
    "unterminated double quote": (
        'A="oops\nB=2\n',
        {
            "node": '"oops',
            "npm-dotenv": '"oops',
            "ruby-dotenv": '"oops',
            "python-dotenv": ABSENT,
            "compose": REJECTED,
            "bash": ABSENT,
        },
    ),
}


def _cases():
    for label, (body, expected) in CASES.items():
        for engine_name, want in expected.items():
            yield pytest.param(body, engine_name, want, id=f"{label} :: {engine_name}")


@pytest.mark.engine
@pytest.mark.parametrize("body,engine_name,want", list(_cases()))
def test_engine_behaviour(envfile, body, engine_name, want):
    engine = BY_NAME[engine_name]
    why = engine.available()
    if why is not None:
        pytest.skip(f"{engine_name}: {why}")

    result = parse(engine_name, envfile(body))

    if want is REJECTED:
        assert result.error is not None, f"expected a rejection, got {result.values!r}"
        return

    assert result.error is None, f"{engine_name} rejected the file: {result.error}"
    assert result.values is not None
    if want is ABSENT:
        assert "A" not in result.values, f"expected no A, got {result.values['A']!r}"
    else:
        assert result.values.get("A") == want


# --- the properties, rather than the table ---------------------------------


@pytest.mark.engine
def test_compose_does_not_report_a_dollar_the_file_does_not_contain(envfile):
    """`docker compose config` doubles every literal `$` on the way out."""
    engine = BY_NAME["compose"]
    if engine.available() is not None:
        pytest.skip("docker is not installed")
    result = parse("compose", envfile("A=100$\nB=a$$b\n"))
    if result.error:
        pytest.skip(f"compose: {result.error}")
    assert result.values["A"] == "100$"
    assert result.values["B"] == "a$b"


@pytest.mark.engine
def test_bash_reports_the_line_it_could_not_run(envfile):
    if BY_NAME["bash"].available() is not None:
        pytest.skip("bash is not installed")
    result = parse("bash", envfile("A=a b\nC=ok\n"))
    # `.` returns the status of the *last* line, which succeeded, so a non-zero
    # exit is not what gives this away -- the complaint on stderr is.
    assert result.values == {"C": "ok"}
    assert result.note is not None
    assert "command not found" in result.note


@pytest.mark.engine
def test_bash_does_not_leak_envdrifts_own_variables(envfile):
    """The helper runs under `set -a`; anything it assigns would be exported."""
    if BY_NAME["bash"].available() is not None:
        pytest.skip("bash is not installed")
    result = parse("bash", envfile("A=1\n"))
    assert result.values == {"A": "1"}


@pytest.mark.engine
def test_bash_starts_from_an_empty_environment(envfile, monkeypatch):
    """A value that interpolates a host variable must not pick one up."""
    if BY_NAME["bash"].available() is not None:
        pytest.skip("bash is not installed")
    monkeypatch.setenv("ENVDRIFT_SHOULD_NOT_LEAK", "leaked")
    result = parse("bash", envfile('A="${ENVDRIFT_SHOULD_NOT_LEAK:-unset}"\n'))
    assert result.values["A"] == "unset"


@pytest.mark.engine
def test_a_file_a_parser_cannot_read_is_an_error_not_a_crash(envfile):
    """Whatever happens, an engine returns a Result."""
    path = envfile('A="oops\n')
    for name in BY_NAME:
        if BY_NAME[name].available() is not None:
            continue
        result = BY_NAME[name].run(path)
        assert result.engine == name
        assert result.values is not None or result.error or result.unavailable


@pytest.mark.engine
def test_python_dotenv_distinguishes_a_bare_key(envfile):
    result = parse("python-dotenv", envfile("A\nB=2\n"))
    assert "A" not in result.values
    assert result.valueless_keys == ("A",)

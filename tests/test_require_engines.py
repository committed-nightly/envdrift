"""The switch that decides whether a missing parser is silence or a failure.

Tested because the whole point of it is that nothing downstream can tell the
difference: a suite that skipped every engine test and a suite that compared
six parsers both print `0 failed` and exit 0. If this switch stops working,
CI goes back to being green for the wrong reason and says nothing about it.
"""

import pytest

from . import conftest


def _outcome(engine: str, why: str) -> tuple[str, str]:
    """Which of the two things `absent()` did, as a plain string.

    Deliberately not `pytest.raises(pytest.fail.Exception)`. A skip raised
    inside that propagates as a skip, so the test meant to prove skipping had
    stopped would itself be *skipped* and the suite would still exit 0 --
    which is this file's own subject, and is how the first version of this
    file behaved. Catching both outcomes and turning either into an ordinary
    assertion is what makes the failure visible.
    """
    try:
        conftest.absent(engine, why)
    except pytest.fail.Exception as exc:
        return "fail", str(exc)
    except pytest.skip.Exception as exc:
        return "skip", str(exc)
    raise AssertionError("absent() returned instead of skipping or failing")


REASON = "the `dotenv` gem is not installed"


def test_a_missing_engine_skips_by_default(monkeypatch):
    monkeypatch.delenv(conftest.REQUIRE_ENV, raising=False)
    outcome, message = _outcome("ruby-dotenv", REASON)
    assert outcome == "skip", message
    assert "ruby-dotenv" in message
    assert REASON in message


def test_a_missing_engine_fails_when_required(monkeypatch):
    monkeypatch.setenv(conftest.REQUIRE_ENV, "1")
    outcome, message = _outcome("ruby-dotenv", REASON)
    assert outcome == "fail", f"absent() {outcome}ped instead of failing: {message}"
    # The engine and the reason both have to survive into the failure: this is
    # the only place CI will say which parser went quiet.
    assert "ruby-dotenv" in message
    assert REASON in message
    assert conftest.REQUIRE_ENV in message


@pytest.mark.parametrize("value", ["", "0"])
def test_unset_shaped_values_leave_skipping_alone(monkeypatch, value):
    """`ENVDRIFT_REQUIRE_ENGINES=` in a shell is a common way to mean 'no'."""
    monkeypatch.setenv(conftest.REQUIRE_ENV, value)
    assert conftest.require_engines() is False
    assert _outcome("ruby-dotenv", REASON)[0] == "skip"


@pytest.mark.parametrize("value", ["1", "yes", "true"])
def test_anything_else_means_required(monkeypatch, value):
    monkeypatch.setenv(conftest.REQUIRE_ENV, value)
    assert conftest.require_engines() is True
    assert _outcome("ruby-dotenv", REASON)[0] == "fail"

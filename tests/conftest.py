import os

import pytest

from envdrift.engines import BY_NAME

#: Set this to make a missing parser a failure instead of a skip.
REQUIRE_ENV = "ENVDRIFT_REQUIRE_ENGINES"


@pytest.fixture
def envfile(tmp_path):
    """Write a .env file verbatim -- no trailing newline is added for you.

    Several of the differences envdrift exists to find are about bytes at the
    end of a line, so the fixture must not tidy anything up.
    """

    def write(body: str, name: str = ".env"):
        path = tmp_path / name
        path.write_bytes(body.encode("utf-8"))
        return path

    return write


def require_engines() -> bool:
    return os.environ.get(REQUIRE_ENV, "") not in ("", "0")


def absent(engine: str, why: str):
    """An engine is not installed. Skip, or fail if we were told to.

    A skipped engine test is silence, and silence reads the same as agreement
    -- the suite goes green having compared nothing. On a laptop with no ruby
    on it, skipping is the right trade and the reason prints under `-rs`.

    In CI it is the wrong trade, and nothing above this line can tell the
    difference: `envdrift --list-engines` answers for the *runtime* only and
    says so in its own output, so it reports six engines `ready` on a box
    where not one of the three parser libraries is installed. Measured: 31 of
    147 tests skip there and the suite still exits 0. Setting
    ENVDRIFT_REQUIRE_ENGINES=1 turns each of those skips into a failure that
    names the engine and the reason.
    """
    message = f"{engine}: {why}"
    if require_engines():
        pytest.fail(f"{message} [{REQUIRE_ENV} is set]", pytrace=False)
    pytest.skip(message)


def unavailable(name: str) -> str | None:
    """The reason the named engine's runtime is missing, or None."""
    return BY_NAME[name].available()


def parse(name: str, path):
    """Run one engine, skipping the test if its library turns out to be missing.

    The runtime being on PATH is not the same as the library being installed,
    and only running it finds that out.
    """
    why = unavailable(name)
    if why is not None:
        absent(name, why)
    result = BY_NAME[name].run(path)
    if result.unavailable is not None:
        absent(name, result.unavailable)
    return result

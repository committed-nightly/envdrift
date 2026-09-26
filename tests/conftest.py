import pytest

from envdrift.engines import BY_NAME


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


@pytest.fixture
def engine(request):
    """An engine by name, skipping the test if it cannot run here."""
    name = request.param
    eng = BY_NAME[name]
    why = eng.available()
    if why is not None:
        pytest.skip(f"{name}: {why}")
    return eng


def requires(name: str):
    """Skip unless the named engine's runtime is present AND its library loads."""
    eng = BY_NAME[name]
    why = eng.available()
    if why is not None:
        return pytest.mark.skip(reason=f"{name}: {why}")
    return pytest.mark.engine


def parse(name: str, path):
    """Run one engine, skipping the test if its library turns out to be missing.

    The runtime being on PATH is not the same as the library being installed,
    and only running it finds that out.
    """
    result = BY_NAME[name].run(path)
    if result.unavailable is not None:
        pytest.skip(f"{name}: {result.unavailable}")
    return result

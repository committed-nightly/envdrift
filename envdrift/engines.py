"""The parsers envdrift knows how to ask, and how to ask them.

Every engine answers the same question -- "what mapping does this file mean?" --
and returns a Result. An engine that is not installed says so by name; it is
never quietly dropped from the comparison, because a parser missing from the
table looks exactly like a parser that agreed.

Availability is decided by looking for a file on disk (shutil.which), never by
running the command and seeing whether it answers. A shell function or alias
called `node` will answer `node --version` perfectly convincingly while no node
binary exists anywhere on the path.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

HELPERS = Path(__file__).parent / "helpers"

DEFAULT_TIMEOUT = 30


@dataclass(frozen=True)
class Result:
    """What one engine made of one file."""

    engine: str
    values: dict[str, str] | None = None
    error: str | None = None
    #: Set when the engine was never run. Distinct from an error: the engine did
    #: not reject the file, it never saw it.
    unavailable: str | None = None
    #: Set when envdrift deliberately held the engine back (see hazards.py).
    held_back: str | None = None
    version: str | None = None
    #: Keys the engine accepted without a value at all, e.g. a bare `KEY` line.
    valueless_keys: tuple[str, ...] = ()
    #: The engine produced values *and* complained. Worth printing: `set -a; .
    #: file` on `A=a b` assigns A=a and then reports `b: command not found`.
    note: str | None = None

    @property
    def ran(self) -> bool:
        return self.values is not None

    @property
    def skipped(self) -> bool:
        return self.unavailable is not None or self.held_back is not None


@dataclass(frozen=True)
class Engine:
    name: str
    #: One line for --list-engines and the report footer.
    what: str
    #: Executable that must exist as a real file for this engine to run.
    requires: str
    run: Callable[[Path], Result] = field(repr=False, default=None)  # type: ignore[assignment]
    #: Constructs in the raw file that this engine will *execute* rather than
    #: read. Empty for a parser that only ever produces strings.
    executes: tuple[str, ...] = ()
    #: What to call `requires` in a message, when the path is not the point.
    requires_label: str = ""

    def available(self) -> str | None:
        """None if the runtime is there, else the reason it is not.

        This only answers for the runtime. Whether the *library* is installed --
        the `dotenv` gem, the `dotenv` package -- is something only the helper
        can find out, and it reports that back as `unavailable` too.
        """
        if shutil.which(self.requires) is None:
            return f"{self.requires_label or self.requires} is not on PATH"
        return None


def _clean_env() -> dict[str, str]:
    """A minimal environment for every engine.

    Some of these parsers consult the ambient environment when a value
    interpolates a name the file does not define, and some do not. Handing them
    all the same near-empty environment keeps that difference from showing up as
    a disagreement about the file.
    """
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "SystemRoot", "NODE_PATH", "GEM_HOME", "GEM_PATH")
    env = {k: v for k, v in os.environ.items() if k in keep}
    env.setdefault("PATH", os.defpath)
    # Stop Node and Ruby volunteering advice on stdout.
    env["NODE_NO_WARNINGS"] = "1"
    env["RUBYOPT"] = "-W0"
    return env


def _run_json_helper(name: str, argv: list[str], timeout: int) -> Result:
    """Run a helper that prints one JSON object and exits 0."""
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_clean_env(),
        )
    except subprocess.TimeoutExpired:
        return Result(name, error=f"timed out after {timeout}s")
    except OSError as exc:
        return Result(name, unavailable=str(exc))

    raw = proc.stdout.strip()
    if not raw:
        detail = proc.stderr.strip().splitlines()
        tail = detail[-1] if detail else f"exit {proc.returncode}, no output"
        return Result(name, error=tail[:300])
    try:
        payload = json.loads(raw.splitlines()[-1])
    except json.JSONDecodeError:
        return Result(name, error=f"helper printed something that is not JSON: {raw[:120]!r}")

    if "unavailable" in payload:
        # The runtime is installed but the library it needs is not. That is not
        # the parser rejecting the file, and must not be scored as a difference.
        return Result(name, unavailable=str(payload["unavailable"])[:300])
    if "error" in payload:
        return Result(name, error=str(payload["error"])[:300])
    values = payload.get("values")
    if not isinstance(values, dict):
        return Result(name, error="helper returned no values")
    return Result(
        name,
        values={str(k): str(v) for k, v in values.items()},
        version=payload.get("version"),
        valueless_keys=tuple(payload.get("valueless_keys") or ()),
    )


def _node_native(path: Path) -> Result:
    return _run_json_helper(
        "node", ["node", str(HELPERS / "node_native.js"), str(path)], DEFAULT_TIMEOUT
    )


def _node_dotenv(path: Path) -> Result:
    return _run_json_helper(
        "npm-dotenv", ["node", str(HELPERS / "node_dotenv.js"), str(path)], DEFAULT_TIMEOUT
    )


def _python_dotenv(path: Path) -> Result:
    return _run_json_helper(
        "python-dotenv",
        [sys.executable, str(HELPERS / "python_dotenv.py"), str(path)],
        DEFAULT_TIMEOUT,
    )


def _ruby_dotenv(path: Path) -> Result:
    return _run_json_helper(
        "ruby-dotenv", ["ruby", str(HELPERS / "ruby_dotenv.rb"), str(path)], DEFAULT_TIMEOUT
    )


def _unescape_compose(value: str) -> str:
    """Undo the `$` doubling in `docker compose config` output.

    Compose prints its resolved config so that feeding it back in produces the
    same thing, which means every literal `$` comes back as `$$`. Reading that
    output as the value would report a `$` the file does not contain.
    """
    return value.replace("$$", "$")


def _compose(path: Path) -> Result:
    """Docker Compose's env_file reader, via `docker compose config`.

    This is the parser that runs when a service says `env_file: .env`, which is
    not the same code path as the `.env` Compose reads for interpolating the
    compose file itself.
    """
    name = "compose"
    target = path.resolve()
    # A dedicated directory, because Compose also picks up a `.env` sitting next
    # to the compose file and uses it for interpolation -- which would be a
    # second, different reading of the same file mixed into the answer.
    with tempfile.TemporaryDirectory(prefix="envdrift-compose-") as tmp:
        compose_file = Path(tmp) / "docker-compose.yaml"
        compose_file.write_text(
            json.dumps(
                {
                    "services": {
                        "envdrift": {"image": "busybox", "env_file": [str(target)]}
                    }
                }
            ),
            encoding="utf-8",
        )
        try:
            proc = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(compose_file),
                    "--project-name",
                    "envdrift",
                    "config",
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                timeout=DEFAULT_TIMEOUT,
                env=_clean_env(),
            )
        except subprocess.TimeoutExpired:
            return Result(name, error=f"timed out after {DEFAULT_TIMEOUT}s")
        except OSError as exc:
            return Result(name, unavailable=str(exc))

    if proc.returncode != 0:
        lines = [ln for ln in proc.stderr.strip().splitlines() if ln.strip()]
        tail = lines[-1] if lines else f"exit {proc.returncode}"
        if "compose" in tail and "is not a docker command" in tail:
            return Result(name, unavailable="docker has no `compose` subcommand")
        return Result(name, error=tail[:300])

    try:
        config = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return Result(name, error="`docker compose config` did not return JSON")

    env = config.get("services", {}).get("envdrift", {}).get("environment") or {}
    values: dict[str, str] = {}
    valueless: list[str] = []
    for key, value in env.items():
        if value is None:
            # Compose renders a key with no value as null, meaning "pass through
            # from the host" -- not the same as an empty string.
            valueless.append(str(key))
            continue
        values[str(key)] = _unescape_compose(str(value))
    return Result(name, values=values, valueless_keys=tuple(sorted(valueless)))


def _bash_source(path: Path) -> Result:
    name = "bash"
    bash = shutil.which("bash")
    if bash is None:
        return Result(name, unavailable="bash is not on PATH")
    with tempfile.TemporaryDirectory(prefix="envdrift-bash-") as tmp:
        before = Path(tmp) / "before"
        after = Path(tmp) / "after"
        status = Path(tmp) / "status"
        try:
            proc = subprocess.run(
                [
                    "env",
                    "-i",
                    bash,
                    "--noprofile",
                    "--norc",
                    str(HELPERS / "bash_source.sh"),
                    str(path.resolve()),
                    str(before),
                    str(after),
                    str(status),
                ],
                capture_output=True,
                text=True,
                timeout=DEFAULT_TIMEOUT,
                env=_clean_env(),
            )
        except subprocess.TimeoutExpired:
            return Result(name, error=f"timed out after {DEFAULT_TIMEOUT}s")
        except OSError as exc:
            return Result(name, unavailable=str(exc))

        complaints = [ln for ln in proc.stderr.strip().splitlines() if ln.strip()]
        if not after.exists() or not after.stat().st_size:
            # The shell died partway through: the file is not sourceable at all.
            tail = complaints[-1] if complaints else f"source failed (exit {proc.returncode})"
            return Result(name, error=_strip_path(tail, path)[:300])

        pre = _parse_env0(before.read_bytes())
        post = _parse_env0(after.read_bytes())
        source_rc = 0
        if status.exists():
            try:
                source_rc = int(status.read_text().strip() or 0)
            except ValueError:
                source_rc = 0
        # Anything on stderr counts, not just a non-zero status. Sourcing
        # `A=a b\nC=ok` returns 0, because `.` reports the status of the *last*
        # command in the file -- and the complaint about `b` in the middle is
        # the only trace that a line did not do what it looks like it does.
        note = None
        if complaints or source_rc != 0:
            detail = _strip_path(complaints[-1], path) if complaints else ""
            note = f"sourced, exit {source_rc}"
            if detail:
                note += f": {detail}"

    # `_` is bash's own last-argument variable and changes between the two dumps
    # for reasons that have nothing to do with the file.
    post.pop("_", None)
    pre.pop("_", None)
    values = {k: v for k, v in post.items() if pre.get(k) != v}
    return Result(name, values=values, note=note)


def _strip_path(message: str, path: Path) -> str:
    """Drop the tmp-file path bash prefixes to its diagnostics.

    It is a path envdrift chose, not one the user would recognise, and it makes
    otherwise identical messages look different between runs.
    """
    for candidate in (str(path.resolve()), str(path)):
        message = message.replace(candidate + ":", "").replace(candidate, "")
    return message.strip()


def _parse_env0(blob: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    for record in blob.split(b"\0"):
        if not record:
            continue
        key, sep, value = record.partition(b"=")
        if not sep:
            continue
        out[key.decode("utf-8", "surrogateescape")] = value.decode("utf-8", "surrogateescape")
    return out


ENGINES: tuple[Engine, ...] = (
    Engine(
        name="node",
        what="Node's built-in util.parseEnv (Node >= 20.12)",
        requires="node",
        run=_node_native,
    ),
    Engine(
        name="npm-dotenv",
        what="the npm `dotenv` package, resolved from the file's directory",
        requires="node",
        run=_node_dotenv,
    ),
    Engine(
        name="python-dotenv",
        what="python-dotenv's dotenv_values()",
        requires=sys.executable,
        requires_label="python3",
        run=_python_dotenv,
    ),
    Engine(
        name="ruby-dotenv",
        what="the Ruby `dotenv` gem's Dotenv.parse",
        requires="ruby",
        run=_ruby_dotenv,
        executes=("$(",),
    ),
    Engine(
        name="compose",
        what="Docker Compose reading the file as a service's env_file",
        requires="docker",
        run=_compose,
    ),
    Engine(
        name="bash",
        what="`set -a; . file`, the way a deploy script reads it",
        requires="bash",
        run=_bash_source,
        executes=("$(", "`"),
    ),
)

BY_NAME = {e.name: e for e in ENGINES}
